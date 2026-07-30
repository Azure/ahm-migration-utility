using System.Net.Http.Headers;
using System.Net.Http.Json;
using Azure.Core;
using Azure.Identity;
using Microsoft.CloudHealth.PreviewMigration.Models.V1;
using Microsoft.Extensions.Logging;
using Spectre.Console;
using Spectre.Console.Cli;

namespace Microsoft.CloudHealth.PreviewMigration;

public class ConvertFromAzureResourceCommand : AsyncCommand<ConvertFromAzureResourceSettings>
{
    public override ValidationResult Validate(CommandContext context, ConvertFromAzureResourceSettings settings)
    {
        if (string.IsNullOrEmpty(settings.ResourceId))
        {
            return ValidationResult.Error("Resource Id is required");
        }

        if (!ResourceIdentifier.TryParse(settings.ResourceId, out var resourceId))
        {
            return ValidationResult.Error("Invalid resource Id");
        }

        if (string.IsNullOrEmpty(settings.OutputFolder))
        {
            return ValidationResult.Error("Output file path is required");
        }

        if (File.Exists(settings.OutputFolder))
        {
            return ValidationResult.Error($"Output folder is a file. Please specify a folder instead - {settings.OutputFolder}");
        }

        return base.Validate(context, settings);
    }

    public override async Task<int> ExecuteAsync(CommandContext context, ConvertFromAzureResourceSettings settings)
    {
        var logger = Utils.CreateLogger();
        logger.LogInformation("Getting access token for ARM...");
        // Deliberately avoid Managed Identity / Workload Identity credentials: this is an
        // interactive developer tool, not an Azure-hosted workload. Probing IMDS
        // (169.254.169.254) just hangs or fails on machines that are not running in Azure.
        // Prefer already-signed-in developer credentials and fall back to interactive browser.
        var tokenCredential = new ChainedTokenCredential(
            new AzureCliCredential(),
            new AzurePowerShellCredential(),
            new VisualStudioCredential(),
            new InteractiveBrowserCredential());
        var token = (await tokenCredential.GetTokenAsync(new TokenRequestContext(["https://management.azure.com/.default"]))).Token;
        var httpClient = new HttpClient();
        var request = new HttpRequestMessage
        {
            RequestUri = new Uri("https://management.azure.com" + settings.ResourceId + "?api-version=2022-11-01-preview"),
            Method = HttpMethod.Get,
            Headers =
            {
                Authorization = new AuthenticationHeaderValue("Bearer", token)
            }
        };
        logger.LogInformation("Getting resource {resourceId}...", settings.ResourceId);
        var responseMessage = await httpClient.SendAsync(request);
        if (!responseMessage.IsSuccessStatusCode)
        {
            logger.LogError("Failed to get resource {resourceId}", settings.ResourceId);
            logger.LogError(await responseMessage.Content.ReadAsStringAsync());
            return 1;
        }

        var v1HealthModel = await responseMessage.Content.ReadFromJsonAsync<HealthModel>();
        if (v1HealthModel == null)
        {
            logger.LogError("Failed to deserialize v1 health model");
            return 1;
        }

        logger.LogInformation("Health model {healthModelName} retrieved from ARM", v1HealthModel.name);

        await BicepFileCreator.CompileAndWriteOutputFile(v1HealthModel, settings.OutputFolder, logger,
            settings.CompileArmTemplate ?? false);

        logger.LogInformation("Health model {healthModelName} converted and written to output folder {outputFolder}", v1HealthModel.name, settings.OutputFolder);

        return 0;
    }
}

public class ConvertFromAzureResourceSettings : Program.ConvertSettings
{
    [CommandOption("-r|--resourceid <resourceId>")]
    public required string ResourceId { get; set; }
}