using Microsoft.CloudHealth.PreviewMigration.Models.V2.Interfaces;

namespace Microsoft.CloudHealth.PreviewMigration.Models.V2;

public class HealthModel : IResourceType
{
    public required string Name { get; set; }
    public string Type => $"{Constants.ProviderNamespace}/{Constants.HealthModelsResourceType}";
    public string ApiVersion => "2026-05-01-preview";

    public string? Location { get; set; }
    public Dictionary<string, string>? Tags { get; set; }
    public Identity? Identity { get; set; }
    public HealthModelProperties? Properties { get; set; }

    public string ToBicepString(
        string symbolicName,
        string? overwriteNameParameter = null,
        string? parent = null,
        IEnumerable<string>? dependsOn = null)
    {
        var locationString = !string.IsNullOrEmpty(Location) ? $"'{Location}'" : "location";
        var dependsOnString = dependsOn == null ? "[]" : "[\n    " + string.Join("\n    ", dependsOn) + "\n  ]";
        var identityString = Identity == null ? "null" : Identity.ToBicepString();
        var tagsString = Tags == null
            ? "null"
            : "{\n    " + string.Join("\n    ", Tags.Select(kvp => $$"""{{kvp.Key}}: '{{kvp.Value}}'""")) + "\n  }";

        var template = $$"""
                         resource {{symbolicName}} '{{Type}}@{{ApiVersion}}' = {
                           name: {{overwriteNameParameter ?? $"'{Name}'"}}
                           location: {{locationString}}
                           identity: {{identityString}}
                           tags: {{tagsString}}
                           properties: {}
                           dependsOn: {{dependsOnString}}
                         }
                         """;

        return template;
    }
}

public class HealthModelProperties : IResourceProperties
{
}

public class Identity
{
    public required string Type { get; set; }
    public Dictionary<string, object>? UserAssignedIdentities { get; set; }

    public string ToBicepString()
    {
        var userMi = UserAssignedIdentities == null
            ? "null"
            : "{\n      " + string.Join("\n      ", UserAssignedIdentities.Select(kvp => $$"""'{{kvp.Key}}': {}""")) +
              "\n    }";
        var template = $$"""
                         {
                             type: '{{Type}}'
                             userAssignedIdentities: {{userMi}}
                           }
                         """;
        return template;
    }
}