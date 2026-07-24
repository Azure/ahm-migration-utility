using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Console;

namespace Microsoft.CloudHealth.PreviewMigration;

public static class Utils
{
    public static readonly string[] SupportedV2Locations =
    [
        "canadacentral", "australiaeast", "centralus", "eastasia", "eastus", "eastus2",
        "germanywestcentral", "italynorth", "northeurope", "southeastasia",
        "swedencentral", "switzerlandnorth", "uksouth"
    ];
    
    public static Guid GenerateDeterministicGuid(this string input)
    {
        var inputBytes = Encoding.UTF8.GetBytes(input);
        var hashBytes = SHA256.HashData(inputBytes);
        var guidBytes = new byte[16];
        Array.Copy(hashBytes, guidBytes, 16);
        return new Guid(guidBytes);
    }

    public static ILogger CreateLogger()
    {
        using var loggerFactory = LoggerFactory.Create(builder =>
        {
            builder
                .AddFilter("Microsoft", LogLevel.Warning)
                .AddFilter("System", LogLevel.Warning)
                .AddFilter("Program", LogLevel.Debug)
                .AddSimpleConsole(options =>
                {
                    options.IncludeScopes = false;
                    options.SingleLine = true;
                    options.UseUtcTimestamp = true;
                    options.ColorBehavior = LoggerColorBehavior.Disabled;
                    //options.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.ffff ";
                });
        });
        return loggerFactory.CreateLogger("HealthModelConverter");
    }
}