// The VM that runs everything except the web app and Foundry (PRD 18.9, 18.10; ADR 0006): Ubuntu 24.04 with
// deploy/cloud-init.yaml as its user data, a public address with an Azure host name for Caddy's certificate, a
// network open to SSH, HTTP and HTTPS only, and a managed identity that signs in to Foundry with no secret.
// main.bicep deploys it with Foundry.

@description('Where the VM lives. It must be a region the subscription allows (Azure for Students limits them).')
param location string = resourceGroup().location

@description('The VM\'s name, which also names its disk, network and address.')
param name string = 'offball-vm'

@description('The VM size. With a live match the stack uses about 1.3 GB, so 2 vCPUs and 4 GB is enough.')
param size string = 'Standard_B2als_v2'

@description('The user you sign in as over SSH.')
param adminUsername string = 'offball'

@description('Your SSH public key, such as the contents of ~/.ssh/id_ed25519.pub. The VM takes no passwords.')
param sshPublicKey string

@description('The first part of the VM\'s host name, <label>.<region>.cloudapp.azure.com. Must be unique in the region.')
param dnsLabel string = 'offball-${uniqueString(resourceGroup().id)}'

@description('The OS disk in GB: enough for Ubuntu, two releases of the image and the match data.')
param diskSizeGB int = 32

var tags = {
  project: 'offball'
  purpose: 'Microsoft AI hackathon submission; all match data is synthetic'
}

// The same ports ufw opens in cloud-init.yaml (PRD 18.12).
var openPorts = [
  { name: 'ssh', protocol: 'Tcp', port: '22' }
  { name: 'http', protocol: 'Tcp', port: '80' }
  { name: 'https', protocol: 'Tcp', port: '443' }
  { name: 'https-quic', protocol: 'Udp', port: '443' }
]

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${name}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      for (p, i) in openPorts: {
        name: 'allow-${p.name}'
        properties: {
          priority: 100 + i * 10
          direction: 'Inbound'
          access: 'Allow'
          protocol: p.protocol
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: p.port
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: ['10.40.0.0/24']
    }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.40.0.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource ip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${name}-ip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    dnsSettings: {
      domainNameLabel: dnsLabel
    }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${name}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          subnet: {
            id: vnet.properties.subnets[0].id
          }
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: ip.id
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: name
  location: location
  tags: tags
  // Signs in to Foundry, and Azure MCP Server to Foundry's metrics, with no key or certificate on the VM.
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: size
    }
    osProfile: {
      computerName: name
      adminUsername: adminUsername
      customData: base64(loadTextContent('../deploy/cloud-init.yaml'))
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        name: '${name}-os'
        createOption: 'FromImage'
        diskSizeGB: diskSizeGB
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
        deleteOption: 'Delete'
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    // The serial console, for when SSH doesn't answer.
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

output principalId string = vm.identity.principalId
@description('The API\'s host name, for up.sh --host.')
output hostName string = ip.properties.dnsSettings.fqdn
output ssh string = 'ssh ${adminUsername}@${ip.properties.dnsSettings.fqdn}'
