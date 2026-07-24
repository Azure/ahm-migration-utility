using System.Text;
using Microsoft.CloudHealth.PreviewMigration.Models.V2.Interfaces;

namespace Microsoft.CloudHealth.PreviewMigration.Models.V2;

public class Entity : IResourceType
{
    public required string Name { get; set; }
    public string Type => $"{Constants.ProviderNamespace}/{Constants.HealthModelsResourceType}/entities";
    public string ApiVersion => "2026-05-01-preview";

    public required EntityProperties Properties { get; set; }

    public string ToBicepString(string symbolicName,
        string? overwriteNameParameter = null, string? parent = null,
        IEnumerable<string>? dependsOn = null)
    {
        ArgumentNullException.ThrowIfNull(parent);

        var dependsOnString = dependsOn == null || !dependsOn.Any()
            ? "[]"
            : "[\n    " + string.Join("\n    ", dependsOn) + "\n  ]";

        var template = $$"""
                         resource {{symbolicName}} '{{Type}}@{{ApiVersion}}' = {
                           parent: {{parent}}
                           name: {{overwriteNameParameter ?? $"'{Name}'"}}
                           properties: {{Properties.ToBicepString()}}
                           dependsOn: {{dependsOnString}}
                         }
                         """;

        return template;
    }
}

public class EntityProperties : IResourceProperties
{
    public string? DisplayName { get; set; }
    public string Impact { get; set; } = "Standard";
    public CanvasPosition? CanvasPosition { get; set; }

    public SignalGroups? SignalGroups { get; set; }

    public string ToBicepString()
    {
        var canvasPositionString = CanvasPosition == null
            ? "null"
            : $$"""
                {
                        x: {{CanvasPosition.X}}
                        y: {{CanvasPosition.Y}}
                      }
                """;

        var template = $$"""
                         {
                               displayName: '{{DisplayName}}'
                               impact: '{{Impact}}'
                               canvasPosition: {{canvasPositionString}}
                               signalGroups: {{(SignalGroups == null ? "null" : SignalGroups.ToBicepString())}}
                           }
                         """;

        return template;
    }
}

public class SignalGroups
{
    public AzureResourceSignalGroup? AzureResource { get; set; }
    public LogAnalyticsSignalGroup? AzureLogAnalytics { get; set; }
    public AzureMonitorWorkspaceSignalGroup? AzureMonitorWorkspace { get; set; }

    public string ToBicepString()
    {
        var azureResourceString = AzureResource == null
            ? "null"
            : $$"""
                {
                          azureResourceId: '{{AzureResource.AzureResourceId}}'
                          authenticationSetting: {{AzureResource.AuthenticationSettingSymbolicName}}.name
                          signals: {{AzureResource.SignalsToBicepString()}}
                        }
                """;

        var logAnalyticsString = AzureLogAnalytics == null
            ? "null"
            : $$"""
                {
                          logAnalyticsWorkspaceResourceId: '{{AzureLogAnalytics.LogAnalyticsWorkspaceResourceId}}'
                          authenticationSetting: {{AzureLogAnalytics.AuthenticationSettingSymbolicName}}.name
                          signals: {{AzureLogAnalytics.SignalsToBicepString()}}
                        }
                """;

        var amwString = AzureMonitorWorkspace == null
            ? "null"
            : $$"""
                {
                          azureMonitorWorkspaceResourceId: '{{AzureMonitorWorkspace.AzureMonitorWorkspaceResourceId}}'
                          authenticationSetting: {{AzureMonitorWorkspace.AuthenticationSettingSymbolicName}}.name
                          signals: {{AzureMonitorWorkspace.SignalsToBicepString()}}
                        }
                """;

        var template = $$"""
                         {
                                 azureResource: {{azureResourceString}}
                                 azureLogAnalytics: {{logAnalyticsString}}
                                 azureMonitorWorkspace: {{amwString}}
                             }
                         """;

        return template;
    }
}

#region Signal Groups

public class AzureResourceSignalGroup
{
    public required string AuthenticationSettingSymbolicName { get; set; }
    public required string AzureResourceId { get; set; }
    public List<AzureResourceSignalInstance>? Signals { get; set; }

    public string SignalsToBicepString()
    {
        if (Signals == null || Signals.Count == 0) return "null";
        var sb = new StringBuilder();
        sb.Append("[\n");
        foreach (var s in Signals)
        {
            sb.Append(s.ToBicepString());
            sb.Append('\n');
        }
        sb.Append("          ]");
        return sb.ToString();
    }
}

public class LogAnalyticsSignalGroup
{
    public required string AuthenticationSettingSymbolicName { get; set; }
    public required string LogAnalyticsWorkspaceResourceId { get; set; }
    public List<LogAnalyticsSignalInstance>? Signals { get; set; }

    public string SignalsToBicepString()
    {
        if (Signals == null || Signals.Count == 0) return "null";
        var sb = new StringBuilder();
        sb.Append("[\n");
        foreach (var s in Signals)
        {
            sb.Append(s.ToBicepString());
            sb.Append('\n');
        }
        sb.Append("          ]");
        return sb.ToString();
    }
}

public class AzureMonitorWorkspaceSignalGroup
{
    public required string AuthenticationSettingSymbolicName { get; set; }
    public required string AzureMonitorWorkspaceResourceId { get; set; }
    public List<PrometheusSignalInstance>? Signals { get; set; }

    public string SignalsToBicepString()
    {
        if (Signals == null || Signals.Count == 0) return "null";
        var sb = new StringBuilder();
        sb.Append("[\n");
        foreach (var s in Signals)
        {
            sb.Append(s.ToBicepString());
            sb.Append('\n');
        }
        sb.Append("          ]");
        return sb.ToString();
    }
}

#endregion

#region Signal Instances

public class EvaluationRules
{
    public required ThresholdRule UnhealthyRule { get; set; }
    public ThresholdRule? DegradedRule { get; set; }

    public string ToBicepString()
    {
        var degradedRuleString = DegradedRule == null
            ? ""
            : $$"""

                                    degradedRule: {
                                      operator: '{{DegradedRule.Operator}}'
                                      threshold: {{DegradedRule.Threshold}}
                                    }
                """;

        return $$"""
                 {
                                    unhealthyRule: {
                                      operator: '{{UnhealthyRule.Operator}}'
                                      threshold: {{UnhealthyRule.Threshold}}
                                    }{{degradedRuleString}}
                                  }
                 """;
    }
}

public class ThresholdRule
{
    public required string Operator { get; set; }
    public required double Threshold { get; set; }
}

public class AzureResourceSignalInstance
{
    public required string Name { get; set; }
    public string? DisplayName { get; set; }
    public string? DataUnit { get; set; }
    public required string MetricNamespace { get; set; }
    public required string MetricName { get; set; }
    public required string TimeGrain { get; set; }
    public string RefreshInterval { get; set; } = "PT1M";
    public required string AggregationType { get; set; }
    public string? DimensionFilter { get; set; }
    public required EvaluationRules EvaluationRules { get; set; }

    public string ToBicepString()
    {
        return $$"""
                                    {
                                      signalKind: 'AzureResourceMetric'
                                      name: '{{Name}}'
                                      displayName: '{{DisplayName ?? MetricName}}'
                                      dataUnit: {{(DataUnit == null ? "null" : "'" + DataUnit + "'")}}
                                      metricNamespace: '{{MetricNamespace}}'
                                      metricName: '{{MetricName}}'
                                      timeGrain: '{{TimeGrain}}'
                                      refreshInterval: '{{RefreshInterval}}'
                                      aggregationType: '{{AggregationType}}'
                                      dimensionFilter: {{(DimensionFilter == null ? "null" : "'" + DimensionFilter + "'")}}
                                      evaluationRules: {{EvaluationRules.ToBicepString()}}
                                    }
                 """;
    }
}

public class LogAnalyticsSignalInstance
{
    public required string Name { get; set; }
    public string? DisplayName { get; set; }
    public string? DataUnit { get; set; }
    public required string QueryText { get; set; }
    public string? TimeGrain { get; set; }
    public string RefreshInterval { get; set; } = "PT1M";
    public string? ValueColumnName { get; set; }
    public required EvaluationRules EvaluationRules { get; set; }

    public string ToBicepString()
    {
        return $$"""
                                    {
                                      signalKind: 'LogAnalyticsQuery'
                                      name: '{{Name}}'
                                      displayName: '{{DisplayName ?? Name}}'
                                      dataUnit: {{(DataUnit == null ? "null" : "'" + DataUnit + "'")}}
                                      queryText: '{{QueryText.Replace("\n", "\\n")}}'
                                      valueColumnName: {{(ValueColumnName == null ? "null" : "'" + ValueColumnName + "'")}}
                                      timeGrain: {{(TimeGrain == null ? "null" : "'" + TimeGrain + "'")}}
                                      refreshInterval: '{{RefreshInterval}}'
                                      evaluationRules: {{EvaluationRules.ToBicepString()}}
                                    }
                 """;
    }
}

public class PrometheusSignalInstance
{
    public required string Name { get; set; }
    public string? DisplayName { get; set; }
    public string? DataUnit { get; set; }
    public required string QueryText { get; set; }
    public string? TimeGrain { get; set; }
    public string RefreshInterval { get; set; } = "PT1M";
    public required EvaluationRules EvaluationRules { get; set; }

    public string ToBicepString()
    {
        return $$"""
                                    {
                                      signalKind: 'PrometheusMetricsQuery'
                                      name: '{{Name}}'
                                      displayName: '{{DisplayName ?? Name}}'
                                      dataUnit: {{(DataUnit == null ? "null" : "'" + DataUnit + "'")}}
                                      queryText: '{{QueryText.Replace("\n", "\\n")}}'
                                      timeGrain: {{(TimeGrain == null ? "null" : "'" + TimeGrain + "'")}}
                                      refreshInterval: '{{RefreshInterval}}'
                                      evaluationRules: {{EvaluationRules.ToBicepString()}}
                                    }
                 """;
    }
}

#endregion

public class CanvasPosition
{
    public int X { get; set; }
    public int Y { get; set; }
}