using System.ComponentModel;
using Spectre.Console.Cli;

namespace Microsoft.CloudHealth.PreviewMigration;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        args = NormalizeOptionNameCasing(args);

        var app = new CommandApp();

        app.Configure(config =>
        {
            config.AddBranch<CommandSettings>("convert", add =>
            {
                add.AddCommand<ConvertFromFileCommand>("file");
                add.AddCommand<ConvertFromAzureResourceCommand>("azure");
            });
        });

        return await app.RunAsync(args);
    }

    /// <summary>
    /// Lowercases the NAME portion of option tokens (e.g. "--ResourceId" -> "--resourceid",
    /// "-R" -> "-r") so command-line options are matched case-insensitively. Option values,
    /// including anything after '=', are left untouched.
    /// </summary>
    private static string[] NormalizeOptionNameCasing(string[] args)
    {
        return args.Select(arg =>
        {
            if (arg.StartsWith("--", StringComparison.Ordinal))
            {
                var eq = arg.IndexOf('=');
                return eq >= 0 ? arg[..eq].ToLowerInvariant() + arg[eq..] : arg.ToLowerInvariant();
            }

            // Short options such as -r/-o/-i (a single dash followed by letters only).
            if (arg.Length > 1 && arg[0] == '-' && arg[1] != '-' && arg.Skip(1).All(char.IsLetter))
            {
                return arg.ToLowerInvariant();
            }

            return arg;
        }).ToArray();
    }

    public class ConvertSettings : CommandSettings
    {
        [CommandOption("-o|--outputfolder <outputFolderPath>")]
        public required string OutputFolder { get; init; }

        [CommandOption("--armtemplate")]
        [DefaultValue(false)]
        public bool? CompileArmTemplate { get; init; }
    }
}