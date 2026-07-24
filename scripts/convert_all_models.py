#!/usr/bin/env python3
"""Convert every Azure Monitor health model (private preview) in a resource group to a
public preview (2026-05-01-preview) Bicep or ARM template using the Python migration
utility.

Enumerates all Microsoft.HealthModel/healthmodels resources in the given resource group
with the Azure CLI, then runs the converter's ``convert azure`` mode for each model and
prints a summary of converted and failed models.

Prerequisites:
  * Azure CLI, logged in via ``az login``.
  * The converter's Azure dependencies: ``pip install -r python/requirements.txt``.

Examples:
  python scripts/convert_all_models.py --subscription <sub> --resource-group my-rg \
      --outputfolder ./out

  python scripts/convert_all_models.py --subscription <sub> --resource-group my-rg \
      --outputfolder ./out --armtemplate
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HEALTH_MODELS_RESOURCE_TYPE = "Microsoft.HealthModel/healthmodels"
DEFAULT_CONVERTER = Path(__file__).resolve().parent.parent / "python" / "health_model_converter.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subscription", required=True,
                        help="Subscription that contains the resource group.")
    parser.add_argument("--resource-group", required=True,
                        help="Resource group to scan for private preview health models.")
    parser.add_argument("--outputfolder", default="./output",
                        help="Folder for generated files (created if missing).")
    parser.add_argument("--armtemplate", action="store_true",
                        help="Emit ARM template JSON instead of Bicep (requires az bicep).")
    parser.add_argument("--converter", default=str(DEFAULT_CONVERTER),
                        help="Path to health_model_converter.py.")
    return parser.parse_args()


def list_model_ids(subscription: str, resource_group: str) -> list[str]:
    """Return the resource IDs of all private preview health models in the group."""
    result = subprocess.run(
        ["az", "resource", "list",
         "--subscription", subscription,
         "--resource-group", resource_group,
         "--resource-type", HEALTH_MODELS_RESOURCE_TYPE,
         "--query", "[].id", "-o", "tsv"],
        capture_output=True, text=True, check=True)
    return [line for line in result.stdout.split() if line]


def main() -> int:
    args = parse_args()

    # The converter authenticates via DefaultAzureCredential. On a developer machine
    # prefer developer credentials (e.g. 'az login') and skip the slow
    # managed-identity/IMDS probe. Set AZURE_TOKEN_CREDENTIALS yourself to override.
    os.environ.setdefault("AZURE_TOKEN_CREDENTIALS", "dev")

    os.makedirs(args.outputfolder, exist_ok=True)

    print(f"Listing health models in resource group '{args.resource_group}'...")
    model_ids = list_model_ids(args.subscription, args.resource_group)
    if not model_ids:
        print(f"No {HEALTH_MODELS_RESOURCE_TYPE} resources found in '{args.resource_group}'.")
        return 0
    print(f"Found {len(model_ids)} health model(s).")

    succeeded: list[str] = []
    failed: list[str] = []
    for resource_id in model_ids:
        name = resource_id.rstrip("/").split("/")[-1]
        print(f"\n=== Converting {name} ===")
        cmd = [sys.executable, args.converter, "convert", "azure",
               "-r", resource_id, "-o", args.outputfolder]
        if args.armtemplate:
            cmd.append("--armtemplate")
        (succeeded if subprocess.run(cmd).returncode == 0 else failed).append(name)

    print("\n==================== Summary ====================")
    print(f"Converted: {len(succeeded)}/{len(model_ids)}")
    if failed:
        print(f"Failed:    {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
