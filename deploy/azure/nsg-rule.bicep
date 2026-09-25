// One inbound rule in the landing zone's public subnet NSG: HTTP and HTTPS from the internet, only to
// the members of our application security group (the demo VM's NIC).
param nsgName string
param ruleName string
param priority int
param destinationAsgId string

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' existing = {
  name: nsgName
}

resource rule 'Microsoft.Network/networkSecurityGroups/securityRules@2024-05-01' = {
  parent: nsg
  name: ruleName
  properties: {
    priority: priority
    direction: 'Inbound'
    access: 'Allow'
    protocol: 'Tcp'
    sourceAddressPrefix: 'Internet'
    sourcePortRange: '*'
    destinationApplicationSecurityGroups: [{ id: destinationAsgId }]
    destinationPortRanges: ['80', '443']
  }
}
