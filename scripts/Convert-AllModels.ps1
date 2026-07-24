<#
.SYNOPSIS
    Convert every Azure Monitor health model (private preview) in a resource group to
    a public preview (2026-05-01-preview) Bicep or ARM template using the .NET
    migration utility.

.DESCRIPTION
    Enumerates all Microsoft.HealthModel/healthmodels resources in the given resource
    group with the Azure CLI, then runs the migration tool's `convert azure` mode for
    each model. A summary of converted and failed models is printed at the end.

    Prerequisites: Azure CLI (logged in via `az login`) and the .NET migration tool
    (either the published .exe or the built .dll run via `dotnet`).

.PARAMETER SubscriptionId
    The subscription that contains the resource group.

.PARAMETER ResourceGroup
    The resource group to scan for private preview health models.

.PARAMETER OutputFolder
    Folder where the generated .bicep / .json files are written. Created if missing.

.PARAMETER ToolPath
    Path to the migration tool. Use the published executable
    (Microsoft.CloudHealth.PreviewMigration.exe) or the built DLL (run via dotnet).

.PARAMETER ArmTemplate
    Emit ARM template JSON instead of Bicep (requires `az bicep`).

.EXAMPLE
    ./Convert-AllModels.ps1 -SubscriptionId <sub> -ResourceGroup my-rg -OutputFolder ./out

.EXAMPLE
    ./Convert-AllModels.ps1 -SubscriptionId <sub> -ResourceGroup my-rg -OutputFolder ./out `
        -ToolPath ./Microsoft.CloudHealth.PreviewMigration.exe -ArmTemplate
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $ResourceGroup,
    [string] $OutputFolder = './output',
    [string] $ToolPath = 'Microsoft.CloudHealth.PreviewMigration.exe',
    [switch] $ArmTemplate
)

$ErrorActionPreference = 'Stop'

# The tool authenticates via DefaultAzureCredential. On a developer machine prefer
# developer credentials (e.g. 'az login') and skip the slow managed-identity/IMDS probe.
# Set AZURE_TOKEN_CREDENTIALS yourself (e.g. 'prod') to override this default.
if (-not $env:AZURE_TOKEN_CREDENTIALS) { $env:AZURE_TOKEN_CREDENTIALS = 'dev' }

New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null

Write-Host "Listing health models in resource group '$ResourceGroup'..."
$ids = az resource list `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroup `
    --resource-type 'Microsoft.HealthModel/healthmodels' `
    --query '[].id' -o tsv

$ids = @($ids -split "`r?`n" | Where-Object { $_ })
if ($ids.Count -eq 0) {
    Write-Warning "No Microsoft.HealthModel/healthmodels resources found in '$ResourceGroup'."
    return
}
Write-Host "Found $($ids.Count) health model(s)."

$succeeded = [System.Collections.Generic.List[string]]::new()
$failed = [System.Collections.Generic.List[string]]::new()

foreach ($id in $ids) {
    $name = ($id -split '/')[-1]
    Write-Host "`n=== Converting $name ===" -ForegroundColor Cyan

    $toolArgs = @('convert', 'azure', '--resourceId', $id, '--outputfolder', $OutputFolder)
    if ($ArmTemplate) { $toolArgs += '--armtemplate' }

    if ($ToolPath -like '*.dll') { & dotnet $ToolPath @toolArgs }
    else { & $ToolPath @toolArgs }

    if ($LASTEXITCODE -eq 0) { $succeeded.Add($name) } else { $failed.Add($name) }
}

Write-Host "`n==================== Summary ===================="
Write-Host "Converted: $($succeeded.Count)/$($ids.Count)" -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host "Failed:    $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
