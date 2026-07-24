using System.IO.Abstractions;
using System.Text;
using Bicep.Core;
using Bicep.Core.Analyzers.Interfaces;
using Bicep.Core.Analyzers.Linter;
using Bicep.Core.Features;
using Bicep.Core.FileSystem;
using Bicep.Core.Registry;
using Bicep.Core.Registry.Auth;
using Bicep.Core.Registry.Catalog;
using Bicep.Core.Registry.Catalog.Implementation.PublicRegistries;
using Bicep.Core.Semantics.Namespaces;
using Bicep.Core.SourceGraph;
using Bicep.Core.TypeSystem.Providers;
using Bicep.Core.Utils;
using Bicep.IO.Abstraction;
using Bicep.IO.FileSystem;
using Microsoft.CloudHealth.PreviewMigration.Models.V2;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using HealthModel = Microsoft.CloudHealth.PreviewMigration.Models.V1.HealthModel;

namespace Microsoft.CloudHealth.PreviewMigration;

public class BicepFileCreator
{
    public static async Task CompileAndWriteOutputFile(HealthModel v1HealthModel,
        string outputFolder,
        ILogger logger, bool compileArmTemplate = false)
    {
        var bicep = ConvertToV2HealthModel(v1HealthModel, logger);

        if (string.IsNullOrEmpty(bicep))
        {
            logger.LogWarning("No bicep output generated for health model {healthModelName}. Skipping writing output file",
                v1HealthModel.name);
            return;
        }

        var output = bicep;

        var extension = ".bicep";

        if (compileArmTemplate)
        {
            output = await CompileBicepToArmTemplate(bicep);
            extension = ".json";
        }

        var outFilePath = Path.Combine(outputFolder, v1HealthModel.name + extension);

        logger.LogInformation("Writing result to output file {outputFile}...", outFilePath);
        Directory.CreateDirectory(outputFolder);
        await File.WriteAllTextAsync(outFilePath, output);
    }

    private static string? ConvertToV2HealthModel(HealthModel v1HealthModel, ILogger logger)
    {
        try
        {
            var location = v1HealthModel.location.ToLower();
            string? locationChangedFrom = null;
            if (!Utils.SupportedV2Locations.Contains(location))
            {
                locationChangedFrom = location;
                logger.LogWarning("Location {location} is not supported in V2. Falling back to {fallbackLocation}",
                    location, Utils.SupportedV2Locations.First());
                location = Utils.SupportedV2Locations.First();
            }

            var resourceNameParameterName = "resourceName";

            var bicepBuilder = new StringBuilder();
            bicepBuilder.AppendLine($"param {resourceNameParameterName} string = '{v1HealthModel.name}'");
            bicepBuilder.AppendLine($"param location string = '{location}'");
            bicepBuilder.AppendLine();

            var v2HealthModel = new Models.V2.HealthModel
            {
                Name = v1HealthModel.name,
                Identity = v1HealthModel.identity != null
                    ? new Models.V2.Identity
                    {
                        Type = v1HealthModel.identity.type,
                        UserAssignedIdentities = v1HealthModel.identity.userAssignedIdentities?.ToDictionary(kvp => kvp.Key,
                            _ => new object())
                    }
                    : null,
                Tags = v1HealthModel.tags,
            };

            var modelSymbolicName = "healthModel";

            bicepBuilder.AppendLine(v2HealthModel.ToBicepString(modelSymbolicName, resourceNameParameterName));
            bicepBuilder.AppendLine();

            if (v1HealthModel.properties.nodes == null)
            {
                logger.LogWarning("No nodes found in v1 health model");
                logger.LogInformation(bicepBuilder.ToString());
                return null;
            }

            // Key: symbolic name, Value: object
            var authenticationSettings = new Dictionary<string, AuthenticationSetting>();
            var entities = new Dictionary<string, Entity>();
            var relationships = new Dictionary<string, Relationship>();

            // Migration summary counters
            int migratedSignalsAzureResource = 0, migratedSignalsLogAnalytics = 0, migratedSignalsPrometheus = 0;
            int skippedDisabledSignals = 0, skippedTextSignals = 0, skippedNestedHealthModelQueries = 0, skippedUnsupportedTypeSignals = 0;
            var skippedUnsupportedTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            if (v1HealthModel.identity != null)
            {
                if (v1HealthModel.identity.type.Contains("SystemAssigned", StringComparison.InvariantCultureIgnoreCase))
                {
                    var authenticationSetting = new AuthenticationSetting
                    {
                        Name = "SystemAssigned",
                        Properties = new ManagedIdentityAuthenticationSettingProperties
                        {
                            DisplayName = "SystemAssigned",
                            ManagedIdentityName = "SystemAssigned"
                        }
                    };
                    var symbolicName = "authenticationSettingSystemAssigned";
                    authenticationSettings.Add(symbolicName, authenticationSetting);
                    bicepBuilder.AppendLine();
                    bicepBuilder.AppendLine(authenticationSetting.ToBicepString(symbolicName, parent: modelSymbolicName));
                }

                if (v1HealthModel.identity.userAssignedIdentities != null)
                {
                    foreach (var userMi in v1HealthModel.identity.userAssignedIdentities)
                    {
                        var userMiName = userMi.Key.Split('/').Last();
                        var authenticationSetting = new AuthenticationSetting
                        {
                            Name = userMi.Key.GenerateDeterministicGuid().ToString(),
                            Properties = new ManagedIdentityAuthenticationSettingProperties
                            {
                                DisplayName = userMiName,
                                ManagedIdentityName = userMi.Key
                            }
                        };
                        var symbolicName = "authenticationSettingUserMi" + authenticationSettings.Count;
                        authenticationSettings.Add(symbolicName, authenticationSetting);
                        bicepBuilder.AppendLine();
                        bicepBuilder.AppendLine(authenticationSetting.ToBicepString(symbolicName, parent: modelSymbolicName));
                    }
                }
            }

            foreach (var node in v1HealthModel.properties.nodes)
            {
                // Special handling for root node
                var isRoot = node.nodeId == "0";
                var nodeName = isRoot ? v2HealthModel.Name : node.nodeId;

                var entity = new Entity
                {
                    Name = nodeName,
                    Properties = new EntityProperties
                    {
                        DisplayName = node.name,
                        Impact = node.impact,
                        HealthObjective = node.healthTargetPercentage,
                        CanvasPosition = node.visual == null
                            ? null
                            : new CanvasPosition
                            {
                                X = node.visual.x,
                                Y = node.visual.y
                            }
                    }
                };

                var dependsOn = new List<string>();

                KeyValuePair<string, AuthenticationSetting>? authenticationSetting = null;
                var queries = node.queries?.Where(q => q.enabledState == "Enabled").ToList();
                skippedDisabledSignals += node.queries?.Count(q => q.enabledState != "Enabled") ?? 0;
                if (queries?.Count > 0)
                {
                    authenticationSetting = authenticationSettings.FirstOrDefault(a =>
                        a.Value.Properties.ManagedIdentityName.EndsWith(node.credentialId, StringComparison.InvariantCultureIgnoreCase));

                    if (authenticationSetting?.Value == null)
                    {
                        logger.LogInformation("No authentication setting found for '{nodeId}'", node.credentialId);
                        authenticationSetting = authenticationSettings.FirstOrDefault();
                        if (authenticationSetting?.Value == null)
                        {
                            logger.LogError("No authentication setting found at all. Cannot convert!");
                            return null;
                        }
                        else
                        {
                            logger.LogWarning("Using default authentication setting '{authSettingName}' for entity {nodeName}.", authenticationSetting.Value.Value.Name, nodeName);
                        }
                    }

                    var signalGroups = new SignalGroups();

                    // Count queries that will not be migrated as signals, by reason.
                    skippedNestedHealthModelQueries += queries.Count(q => q.queryType == "ResourceMetricsQuery"
                        && q.metricNamespace.Equals("microsoft.healthmodel/healthmodels", StringComparison.InvariantCultureIgnoreCase));
                    skippedTextSignals += queries.Count(q => q.dataType == "Text"
                        && (q.queryType == "LogQuery"
                            || (q.queryType == "ResourceMetricsQuery"
                                && !q.metricNamespace.Equals("microsoft.healthmodel/healthmodels", StringComparison.InvariantCultureIgnoreCase))));
                    var unsupportedTypeQueries = queries.Where(q => q.queryType != "ResourceMetricsQuery"
                        && q.queryType != "LogQuery" && q.queryType != "PrometheusMetricsQuery").ToList();
                    skippedUnsupportedTypeSignals += unsupportedTypeQueries.Count;
                    foreach (var q in unsupportedTypeQueries) skippedUnsupportedTypes.Add(q.queryType);

                    // Azure Resource Metric signals
                    var resourceMetricsQueries = queries
                        .Where(q => q.queryType == "ResourceMetricsQuery")
                        .Where(q => !q.metricNamespace.Equals("microsoft.healthmodel/healthmodels",
                            StringComparison.InvariantCultureIgnoreCase))
                        .Where(q => q.dataType != "Text")
                        .ToList();
                    if (resourceMetricsQueries.Count != 0)
                    {
                        var azureResourceId = node.azureResourceId;

                        // Special handling for nested health models
                        if (azureResourceId.Contains("microsoft.healthmodel/healthmodels", StringComparison.InvariantCultureIgnoreCase))
                        {
                            azureResourceId = azureResourceId.Replace(
                                "microsoft.healthmodel/healthmodels", "Microsoft.CloudHealth/healthmodels", StringComparison.InvariantCultureIgnoreCase);
                            logger.LogInformation(
                                "Replacing 'microsoft.healthmodel/healthmodels' with 'Microsoft.CloudHealth/healthmodels' in AzureResourceId for nested health model {nodeName}. Ensure that the nested health model is also being converted and resides in the same resource group as before!",
                                nodeName);
                        }

                        signalGroups.AzureResource = new AzureResourceSignalGroup
                        {
                            AuthenticationSettingSymbolicName = authenticationSetting.Value.Key,
                            AzureResourceId = azureResourceId,
                            Signals = resourceMetricsQueries.Select(q => new AzureResourceSignalInstance
                            {
                                Name = q.queryId,
                                DisplayName = q.metricName,
                                MetricNamespace = q.metricNamespace,
                                MetricName = q.metricName,
                                TimeGrain = q.timeGrain,
                                AggregationType = q.aggregationType,
                                DataUnit = q.dataUnit,
                                DimensionFilter = !string.IsNullOrEmpty(q.dimension) ? (q.dimension + " eq '" + (!string.IsNullOrEmpty(q.dimensionFilter) ? q.dimensionFilter : "*") + "'") : null,
                                EvaluationRules = CreateEvaluationRules(q.unhealthyOperator, q.unhealthyThreshold, q.degradedOperator, q.degradedThreshold)
                            }).ToList()
                        };
                    }

                    // Log Analytics Query signals
                    var logAnalyticsQueries = queries
                        .Where(q => q.queryType == "LogQuery")
                        .Where(q => q.dataType != "Text")
                        .ToList();
                    if (logAnalyticsQueries.Count != 0)
                    {
                        signalGroups.AzureLogAnalytics = new LogAnalyticsSignalGroup
                        {
                            AuthenticationSettingSymbolicName = authenticationSetting.Value.Key,
                            LogAnalyticsWorkspaceResourceId = node.logAnalyticsResourceId,
                            Signals = logAnalyticsQueries.Select(q => new LogAnalyticsSignalInstance
                            {
                                Name = q.queryId,
                                DisplayName = q.name,
                                QueryText = q.queryText,
                                DataUnit = q.dataUnit,
                                TimeGrain = q.timeGrain,
                                ValueColumnName = q.valueColumnName,
                                EvaluationRules = CreateEvaluationRules(q.unhealthyOperator, q.unhealthyThreshold, q.degradedOperator, q.degradedThreshold)
                            }).ToList()
                        };
                    }

                    // Prometheus Metrics Query signals
                    var prometheusQueries = queries
                        .Where(q => q.queryType == "PrometheusMetricsQuery")
                        .ToList();

                    migratedSignalsAzureResource += resourceMetricsQueries.Count;
                    migratedSignalsLogAnalytics += logAnalyticsQueries.Count;
                    migratedSignalsPrometheus += prometheusQueries.Count;
                    if (prometheusQueries.Count != 0)
                    {
                        signalGroups.AzureMonitorWorkspace = new AzureMonitorWorkspaceSignalGroup
                        {
                            AuthenticationSettingSymbolicName = authenticationSetting.Value.Key,
                            AzureMonitorWorkspaceResourceId = node.azureMonitorWorkspaceResourceId,
                            Signals = prometheusQueries.Select(q => new PrometheusSignalInstance
                            {
                                Name = q.queryId,
                                DisplayName = q.name,
                                QueryText = q.queryText,
                                DataUnit = q.dataUnit,
                                TimeGrain = q.timeGrain,
                                EvaluationRules = CreateEvaluationRules(q.unhealthyOperator, q.unhealthyThreshold, q.degradedOperator, q.degradedThreshold)
                            }).ToList()
                        };
                    }

                    entity.Properties.SignalGroups = signalGroups;
                }

                var symbolicName = $"entity{entities.Count}";
                entities.Add(symbolicName, entity);

                bicepBuilder.AppendLine();
                if (isRoot)
                {
                    bicepBuilder.AppendLine(entity.ToBicepString(symbolicName, overwriteNameParameter: resourceNameParameterName, parent: modelSymbolicName, dependsOn: dependsOn));
                }
                else
                {
                    bicepBuilder.AppendLine(entity.ToBicepString(symbolicName, parent: modelSymbolicName, dependsOn: dependsOn));
                }
            }

            foreach (var node in v1HealthModel.properties.nodes)
            {
                var nodeName = node.nodeId == "0" ? v2HealthModel.Name : node.nodeId;
                var childNodeIds = node.childNodeIds;
                if (childNodeIds == null || childNodeIds.Length == 0)
                    continue;
                foreach (var childNodeId in childNodeIds)
                {
                    var parentEntitySymbolicName = entities.First(kvp => kvp.Value.Name == nodeName).Key;
                    var childEntitySymbolicName = entities.First(kvp => kvp.Value.Name == childNodeId).Key;

                    var relationship = new Relationship
                    {
                        Name = $"{nodeName}-{childNodeId}".GenerateDeterministicGuid().ToString(),
                        Properties = new RelationshipProperties
                        {
                            ParentEntityName = nodeName,
                            ChildEntityName = childNodeId
                        },
                        ParentEntitySymbolicName = parentEntitySymbolicName,
                        ChildEntitySymbolicName = childEntitySymbolicName
                    };
                    var symbolicName = $"relationship{relationships.Count}";

                    relationships.Add(symbolicName, relationship);

                    bicepBuilder.AppendLine();
                    bicepBuilder.AppendLine(relationship.ToBicepString(symbolicName, parent: modelSymbolicName));
                }
            }

            var totalSignals = migratedSignalsAzureResource + migratedSignalsLogAnalytics + migratedSignalsPrometheus;
            logger.LogInformation(
                "Migration summary for '{model}': migrated {entities} entities, {relationships} relationships, {signals} signals (azureResourceMetric={arm}, logAnalytics={la}, prometheus={prom}).",
                v1HealthModel.name, entities.Count, relationships.Count, totalSignals,
                migratedSignalsAzureResource, migratedSignalsLogAnalytics, migratedSignalsPrometheus);

            if (skippedDisabledSignals + skippedTextSignals + skippedUnsupportedTypeSignals + skippedNestedHealthModelQueries > 0
                || locationChangedFrom != null)
            {
                logger.LogWarning("Not migrated 1:1 for '{model}':", v1HealthModel.name);
                if (skippedDisabledSignals > 0)
                    logger.LogWarning("  - {count} signal(s) skipped: disabled in source (enabledState != 'Enabled').", skippedDisabledSignals);
                if (skippedTextSignals > 0)
                    logger.LogWarning("  - {count} signal(s) skipped: dataType 'Text' is not supported in public preview (numeric thresholds only).", skippedTextSignals);
                if (skippedUnsupportedTypeSignals > 0)
                    logger.LogWarning("  - {count} signal(s) skipped: unsupported query type(s) [{types}].", skippedUnsupportedTypeSignals, string.Join(", ", skippedUnsupportedTypes));
                if (skippedNestedHealthModelQueries > 0)
                    logger.LogWarning("  - {count} nested health model metric quer(y/ies) re-modeled via entity relationship instead of a signal.", skippedNestedHealthModelQueries);
                if (locationChangedFrom != null)
                    logger.LogWarning("  - location changed from '{from}' to '{to}' (source region not available in public preview).", locationChangedFrom, location);
            }

            return bicepBuilder.ToString();
        }
        catch (Exception e)
        {
            logger.LogError(e, "Failed to convert v1 health model {healthModelName} to v2 Bicep file", v1HealthModel.name);
            return null;
        }
    }

    // Maps Private Preview (v1) signal operator names to the Public Preview
    // (2026-05-01-preview) SignalOperator enum. v1 used Lower*/*Equals spellings.
    private static readonly Dictionary<string, string> OperatorMap = new(StringComparer.OrdinalIgnoreCase)
    {
        ["LowerThan"] = "LessThan",
        ["LessThan"] = "LessThan",
        ["LowerOrEquals"] = "LessThanOrEqual",
        ["LowerThanOrEquals"] = "LessThanOrEqual",
        ["LessThanOrEqual"] = "LessThanOrEqual",
        ["GreaterThan"] = "GreaterThan",
        ["GreaterOrEquals"] = "GreaterThanOrEqual",
        ["GreaterThanOrEquals"] = "GreaterThanOrEqual",
        ["GreaterThanOrEqual"] = "GreaterThanOrEqual",
        ["Equals"] = "Equal",
        ["Equal"] = "Equal",
        ["NotEquals"] = "NotEqual",
        ["NotEqual"] = "NotEqual",
    };

    private static string MapOperator(string v1Operator)
        => OperatorMap.TryGetValue(v1Operator, out var mapped) ? mapped : v1Operator;

    private static EvaluationRules CreateEvaluationRules(
        string unhealthyOperator, string unhealthyThreshold,
        string? degradedOperator, string? degradedThreshold)
    {
        return new EvaluationRules
        {
            UnhealthyRule = new ThresholdRule
            {
                Operator = MapOperator(unhealthyOperator),
                Threshold = double.Parse(unhealthyThreshold)
            },
            DegradedRule = string.IsNullOrEmpty(degradedOperator) || string.IsNullOrEmpty(degradedThreshold)
                ? null
                : new ThresholdRule
                {
                    Operator = MapOperator(degradedOperator),
                    Threshold = double.Parse(degradedThreshold)
                }
        };
    }

    /// <summary>
    /// Compiles the Bicep input to an ARM template JSON string.
    /// </summary>
    /// <param name="bicepInput"></param>
    /// <returns></returns>
    private static async Task<string?> CompileBicepToArmTemplate(string bicepInput)
    {
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, bicepInput);

        var host = Host.CreateDefaultBuilder().ConfigureServices(services =>
        {
            services.AddSingleton<IFileSystem, FileSystem>();
            services.AddSingleton<INamespaceProvider, NamespaceProvider>();
            services.AddSingleton<IResourceTypeProviderFactory, ResourceTypeProviderFactory>();
            services.AddSingleton<IContainerRegistryClientFactory, ContainerRegistryClientFactory>();
            services.AddSingleton<ITemplateSpecRepositoryFactory, TemplateSpecRepositoryFactory>();
            services.AddSingleton<IModuleDispatcher, ModuleDispatcher>();
            services.AddSingleton<IArtifactRegistryProvider, DefaultArtifactRegistryProvider>();
            services.AddSingleton<ITokenCredentialFactory, TokenCredentialFactory>();
            services.AddSingleton<IFileResolver, FileResolver>();
            services.AddSingleton<IFileExplorer, FileSystemFileExplorer>();
            services.AddSingleton<ISourceFileFactory, SourceFileFactory>();
            services.AddSingleton<IAuxiliaryFileCache, AuxiliaryFileCache>();
            services.AddSingleton<IPublicModuleMetadataProvider, PublicModuleMetadataProvider>();
            services.AddSingleton<IPublicModuleIndexHttpClient, PublicModuleMetadataHttpClient>();
            services.AddHttpClient<PublicModuleMetadataHttpClient>();
            services.AddSingleton<IEnvironment, Bicep.Core.Utils.Environment>();
            services
                .AddSingleton<Bicep.Core.Configuration.IConfigurationManager,
                    Bicep.Core.Configuration.ConfigurationManager>();
            services.AddSingleton<IBicepAnalyzer, LinterAnalyzer>();
            services.AddSingleton<IFeatureProviderFactory, FeatureProviderFactory>();
            services.AddSingleton<ILinterRulesProvider, LinterRulesProvider>();
            services.AddSingleton<BicepCompiler>();
        }).Build();

        var bicepCompiler = host.Services.GetRequiredService<BicepCompiler>();
        var compilation = bicepCompiler.CreateCompilationWithoutRestore(new Uri(tempFile, UriKind.Absolute));
        var armTemplate = compilation.Emitter.Template().Template;
        return armTemplate;
    }
}