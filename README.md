# Azure Monitor health models migration utility

This is a simple tool to convert an Azure Monitor health models **Private Preview** configuration to an Azure Monitor health models **Public Preview** configuration (`2026-05-01-preview`). It outputs either a Bicep or ARM template file to deploy a new Public Preview health model resource with all related resource types.

The converter translates Private Preview signal queries directly into inline signal instances on Public Preview entities — no separate signal definition resources are created.

## Prerequisites

### Option 1: .NET Implementation (Windows only)

- .NET 10 runtime installed
- Utility tool binaries downloaded from the **Releases** section of this GitHub repository

### Option 2: Python Implementation (Cross-platform)

- Python 3.9+ installed
- (Optional) Azure SDK dependencies for Azure resource conversion:

  ```bash
  pip install -r python/requirements.txt
  ```

  Note: Azure SDK is only required for direct Azure resource conversion. File-based conversion works without any dependencies.

- (Optional) Azure CLI with Bicep for ARM template generation:

  ```bash
  # Install Azure CLI (if not already installed)
  # See: https://docs.microsoft.com/azure/azure-cli/install-azure-cli
  
  # Install Bicep
  az bicep install
  ```

  Note: Bicep is only required if you want to use the `--armtemplate` switch to generate ARM templates instead of Bicep files.

## Remarks

- The public preview is not available in all the same Azure locations as the private preview version. The migration tool will thus default to another location if your former location is currently not yet supported.
- There are minor scenarios which cannot be migrated 1:1. Watch out in the tool's log output for any warnings.

## Usage

The migration utility is available in two implementations:

- **C#/.NET** (Windows only)
- **Python** (Cross-platform: Windows, macOS, Linux)

Both implementations support two modes:

- **File input** - Convert from exported JSON file (no Azure connection required)
- **Azure direct** - Load private preview configuration directly from Azure

Both implementations produce identical output.

### File input

This method allows to convert a model configuration after it has been manually exported from Azure and stored in a file. The tool will not require any connection/permission to Azure.

- Fetch the health model configuration from the Azure portal:

  ![get resource json](./docs/ahm_v1_json.png)

- Copy the entire JSON definition and store it in a local file, e.g. under **/tmp/v1_input.json**

  ![resource json](./docs/ahm_v1_resource.png)

#### Using .NET tool (Windows only):

```bash
# Generate Bicep file (default)
Microsoft.CloudHealth.PreviewMigration.exe convert file --inputfile /tmp/v1_input.json --outputfolder /tmp

# Generate ARM template
Microsoft.CloudHealth.PreviewMigration.exe convert file --inputfile /tmp/v1_input.json --outputfolder /tmp --armtemplate
```

#### Using Python (Cross-platform):

```bash
# Generate Bicep file (default)
python python/health_model_converter.py convert file -i /tmp/v1_input.json -o /tmp

# Generate ARM template (requires az bicep)
python python/health_model_converter.py convert file -i /tmp/v1_input.json -o /tmp --armtemplate

# Or with long arguments:
python python/health_model_converter.py convert file --inputfile /tmp/v1_input.json --outputfolder /tmp
python python/health_model_converter.py convert file --inputfile /tmp/v1_input.json --outputfolder /tmp --armtemplate
```

### Load private preview configuration from Azure

This method will attempt to fetch the health model directly from Azure, using only a resourceId as input. It requires your current user being logged in using Azure CLI etc.

- Get the resource id of the health model resource

#### Using .NET tool (Windows only):

```bash
# Generate Bicep file (default)
Microsoft.CloudHealth.PreviewMigration.exe convert azure --resourceId /subscriptions/7ddfffd7-abcd-40df-b352-828cbd55d6f4/resourceGroups/demo-rg/providers/Microsoft.HealthModel/healthmodels/my-model --outputfolder /tmp

# Generate ARM template
Microsoft.CloudHealth.PreviewMigration.exe convert azure --resourceId /subscriptions/7ddfffd7-abcd-40df-b352-828cbd55d6f4/resourceGroups/demo-rg/providers/Microsoft.HealthModel/healthmodels/my-model --outputfolder /tmp --armtemplate
```

#### Using Python (Cross-platform):

```bash
# First, ensure you're authenticated with Azure
az login

# Install Azure dependencies (only needed once)
pip install -r python/requirements.txt

# Generate Bicep file (default)
python python/health_model_converter.py convert azure -r /subscriptions/7ddfffd7-abcd-40df-b352-828cbd55d6f4/resourceGroups/demo-rg/providers/Microsoft.HealthModel/healthmodels/my-model -o /tmp

# Generate ARM template (requires az bicep)
python python/health_model_converter.py convert azure -r /subscriptions/7ddfffd7-abcd-40df-b352-828cbd55d6f4/resourceGroups/demo-rg/providers/Microsoft.HealthModel/healthmodels/my-model -o /tmp --armtemplate
```

## Python Script Examples

### Quick Start

```bash
# Navigate to the repository
cd AzureMonitorHealthModels-migration-utility

# File-based conversion to Bicep (no dependencies needed)
python python/health_model_converter.py convert file -i samples/mymodel-v1 -o samples/output

# File-based conversion to ARM template (requires az bicep)
python python/health_model_converter.py convert file -i samples/mymodel-v1 -o samples/output --armtemplate

# Azure resource conversion to Bicep (requires Azure SDK)
pip install -r python/requirements.txt
az login
python python/health_model_converter.py convert azure -r "/subscriptions/.../providers/Microsoft.HealthModel/healthmodels/mymodel" -o samples/output

# Azure resource conversion to ARM template (requires Azure SDK and az bicep)
python python/health_model_converter.py convert azure -r "/subscriptions/.../providers/Microsoft.HealthModel/healthmodels/mymodel" -o samples/output --armtemplate
```

### Help and Usage Information

```bash
# Show general help
python python/health_model_converter.py --help

# Show help for file conversion
python python/health_model_converter.py convert file --help

# Show help for Azure conversion
python python/health_model_converter.py convert azure --help
```

## Deploy new resource to Azure

After you executed the commands above, in your specified output folder you will find a Bicep or ARM template file. You can use that to directly deploy a new health model resource to Azure:

### Output Formats

Both tools support two output formats:

- **Bicep files** (`.bicep`) - Default output format, human-readable and maintainable
- **ARM templates** (`.json`) - Generated using the `--armtemplate` switch, ready for deployment via Azure Portal

### Deploy via CLI

If you have the Azure CLI installed, you can start the deployment like this:

```bash
az account set --subscription <target subscription id>
az deployment group create --resource-group <your target resource group> --template-file <generated-arm-template|bicep file>
```

You can overwrite the default parameters for resource name and location using the `--parameters` argument.

### Deploy via Azure Portal

> This requires that you have run the migration tool with the `--armtemplate` switch. Or you can manually convert a Bicep file: `az bicep build --file <generated bicep file>`

1. In the search box on top of the Portal type **deploy a custom template**

   ![deploy](./docs/portal_deploy.png)

2. Click on **Build your own template in the editor**

3. Click on **Load file** and select your generated ARM template JSON file.

   ![editor](./docs/edit_template.png)

4. Click on Save.

5. Validate the parameters, click on **Review + Create** and start the deployment.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
