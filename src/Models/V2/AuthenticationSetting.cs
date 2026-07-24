using Microsoft.CloudHealth.PreviewMigration.Models.V2.Interfaces;

namespace Microsoft.CloudHealth.PreviewMigration.Models.V2;

public class AuthenticationSetting : IResourceType
{
    public required string Name { get; set; }
    public string Type => $"{Constants.ProviderNamespace}/{Constants.HealthModelsResourceType}/authenticationSettings";
    public string ApiVersion => "2026-05-01-preview";
    public required ManagedIdentityAuthenticationSettingProperties Properties { get; set; }

    public string ToBicepString(string symbolicName,
        string? overwriteNameParameter = null,
        string? parent = null,
        IEnumerable<string>? dependsOn = null)
    {
        ArgumentNullException.ThrowIfNull(parent);

        var dependsOnString = dependsOn == null ? "[]" : "[\n    " + string.Join("\n    ", dependsOn) + "\n  ]";

        var template = $$"""
                         resource {{symbolicName}} '{{Type}}@{{ApiVersion}}' = {
                           parent: {{parent}}
                           name: {{overwriteNameParameter ?? $"'{Name}'"}}
                           properties: {
                             displayName: '{{Properties.DisplayName}}'
                             authenticationKind: '{{Properties.AuthenticationKind}}'
                             managedIdentityName: '{{Properties.ManagedIdentityName}}'
                           }
                           dependsOn: {{dependsOnString}}
                         }
                         """;

        return template;
    }
}

public class ManagedIdentityAuthenticationSettingProperties : IResourceProperties
{
    public string? DisplayName { get; set; }
    public string AuthenticationKind => "ManagedIdentity";
    public required string ManagedIdentityName { get; set; }
}