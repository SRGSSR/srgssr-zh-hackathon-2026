#!/bin/sh
# Remove everything the demo created: its rule in the landing zone's subnet NSG, then the whole
# resource group (VM, disk, IP, NIC, security group). Usage: deploy/azure/teardown.sh [subscription] [resource-group]
set -e
SUB="${1:-z231-as-technology-playground-dev}"; RG="${2:-rg-commune-letter-demo}"
az network nsg rule delete --subscription "$SUB" --resource-group rg-z231-dev \
  --nsg-name nsg-z231-dev-nch-publ-01 --name commune-letter-demo-web
az group delete --subscription "$SUB" --name "$RG" --yes
echo "removed: NSG rule commune-letter-demo-web and resource group $RG"
