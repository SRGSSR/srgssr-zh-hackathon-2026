// Commune letter helper - hackathon demo on Azure, in Switzerland. One Ubuntu VM runs the same
// docker compose stack as the repository, behind Caddy (HTTPS with a Let's Encrypt certificate on the
// VM's Azure DNS name). No SSH port: manage it with `az vm run-command`. The VM joins the landing
// zone's public subnet (our role cannot create networks) and adds one rule to that subnet's NSG, open
// to this VM only. Everything else lives in one resource group; teardown.sh removes the rule and the group.

@description('Switzerland North (Zurich) keeps the gateway and the waiting letters in Switzerland.')
param location string = resourceGroup().location
param repoUrl string = 'https://github.com/SRGSSR/srgssr-zh-hackathon-2026.git'
param branch string = 'public-ai-service'
param vmSize string = 'Standard_D2s_v5'

@description('Public AI API key. Empty: the relay answers with clearly labelled simulated responses.')
@secure()
param publicAiApiKey string = ''

@description('Optional shared password (user "jury"). Empty: the demo is open, with the SHARED_DEMO safeguards.')
@secure()
param demoPassword string = ''

@description('SSH public key of the admin user. Azure requires one; port 22 stays closed.')
param adminPublicKey string

@description('The demo is served at https://<dnsLabel>.<location>.cloudapp.azure.com')
param dnsLabel string = 'commune-letter-${uniqueString(resourceGroup().id)}'

@description('Optional own domains, comma-separated, with DNS already pointing to the VM. The first serves the demo; the others and the Azure name redirect to it.')
param domains string = ''

@description('Changes on every deploy, so the setup script re-runs: pulls the branch, rebuilds, restarts.')
param deployStamp string = utcNow()

param tags object = { Project: 'commune-letter-hackathon' }

@description('The landing zone\'s network, managed centrally.')
param networkResourceGroup string = 'rg-z231-dev'
param vnetName string = 'vnet-z231-dev-nch-01'
param subnetName string = 'snet-z231-dev-nch-publ-01'
param subnetNsgName string = 'nsg-z231-dev-nch-publ-01'
@description('Priority of our rule in the subnet NSG; must be free.')
param rulePriority int = 400

var name = 'commune-letter-demo'

// --- network: the landing zone's public subnet; 80 (certificate challenge) and 443 open to this VM only ---
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: '${vnetName}/${subnetName}'
  scope: resourceGroup(networkResourceGroup)
}

resource asg 'Microsoft.Network/applicationSecurityGroups@2024-05-01' = {
  name: '${name}-asg'
  location: location
  tags: tags
}

module webRule 'nsg-rule.bicep' = {
  name: '${name}-nsg-rule'
  scope: resourceGroup(networkResourceGroup)
  params: {
    nsgName: subnetNsgName
    ruleName: '${name}-web'
    priority: rulePriority
    destinationAsgId: asg.id
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${name}-ip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: { domainNameLabel: dnsLabel }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${name}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: subnet.id }
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: { id: publicIp.id }
          applicationSecurityGroups: [{ id: asg.id }]
        }
      }
    ]
  }
}

// --- instance ---
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    hardwareProfile: { vmSize: vmSize }
    storageProfile: {
      imageReference: { publisher: 'Canonical', offer: 'ubuntu-24_04-lts', sku: 'server', version: 'latest' }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        deleteOption: 'Delete'
      }
    }
    osProfile: {
      computerName: name
      adminUsername: 'azureuser'
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: { publicKeys: [{ path: '/home/azureuser/.ssh/authorized_keys', keyData: adminPublicKey }] }
      }
    }
    networkProfile: { networkInterfaces: [{ id: nic.id, properties: { deleteOption: 'Delete' } }] }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
    }
    diagnosticsProfile: { bootDiagnostics: { enabled: true } }
  }
}

// --- setup: the key and the password travel in protectedSettings (encrypted, decrypted only on the VM) ---
resource setup 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = {
  parent: vm
  name: 'setup'
  dependsOn: [webRule]
  location: location
  tags: tags
  properties: {
    publisher: 'Microsoft.Azure.Extensions'
    type: 'CustomScript'
    typeHandlerVersion: '2.1'
    autoUpgradeMinorVersion: true
    forceUpdateTag: deployStamp
    protectedSettings: {
      script: base64(join([
        '#!/bin/sh'
        'REPO_URL=\'${repoUrl}\''
        'BRANCH=\'${branch}\''
        'SITE_HOST=\'${publicIp.properties.dnsSettings.fqdn}\''
        'DOMAINS=\'${domains}\''
        'KEY_B64=\'${base64(publicAiApiKey)}\''
        'PASS_B64=\'${base64(demoPassword)}\''
        loadTextContent('setup.sh')
      ], '\n'))
    }
  }
}

output url string = 'https://${empty(domains) ? publicIp.properties.dnsSettings.fqdn : first(split(replace(domains, ' ', ''), ','))}'
output ip string = publicIp.properties.ipAddress
output vmName string = vm.name
