// OffBall in one deployment (PRD 18.9, 18.10; ADRs 0006 and 0007): the VM, Microsoft Foundry and the storage
// account whose static website serves the web app, with the VM's managed identity given Foundry's roles, so nothing
// on the VM holds an Azure secret.
//
//   az group create --name offball --location <region>
//   az deployment group create --resource-group offball --template-file infra/main.bicep \
//     --parameters sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" openRouterKey=<key> \
//       foundryLocation=<region> ciPrincipalId=<offball-ci's object ID>
//
// Every region must be one the subscription allows; Azure for Students limits them (deploy/README.md).

@description('Where the VM and the web app live. Defaults to the resource group\'s region.')
param location string = resourceGroup().location

@description('Where Foundry lives, if the VM\'s region doesn\'t offer Foundry Agent Service and its models.')
param foundryLocation string = location

@description('Your SSH public key, such as the contents of ~/.ssh/id_ed25519.pub.')
param sshPublicKey string

@description('Your OpenRouter key (ADR 0004). Kept only in Foundry\'s gateway connection, never in an output.')
@secure()
param openRouterKey string

@description('The VM size: 2 vCPUs and 4 GB by default, about $28 to $35 a month while it runs, by region.')
param vmSize string = 'Standard_B2als_v2'

@description('Object ID of offball-ci\'s service principal, which uploads the web app and runs the evaluations. Empty skips its roles.')
param ciPrincipalId string = ''

@description('Who hears when spending passes the monthly budget. Leave it empty on Azure for Students, which has no budgets.')
param budgetEmails array = []

module vm 'vm.bicep' = {
  name: 'vm'
  params: {
    location: location
    size: vmSize
    sshPublicKey: sshPublicKey
  }
}

// The crews, speech and evaluations, and Azure MCP Server, all sign in as the VM.
module foundry 'foundry.bicep' = {
  name: 'foundry'
  params: {
    location: foundryLocation
    openRouterKey: openRouterKey
    appPrincipalId: vm.outputs.principalId
    azmcpPrincipalId: vm.outputs.principalId
    ciPrincipalId: ciPrincipalId
    budgetEmails: budgetEmails
  }
}

module web 'web.bicep' = {
  name: 'web'
  params: {
    location: location
    ciPrincipalId: ciPrincipalId
  }
}

output ssh string = vm.outputs.ssh
@description('The API\'s host name, for up.sh --host.')
output hostName string = vm.outputs.hostName
@description('The web app\'s storage account, which CI uploads the build to.')
output webAccount string = web.outputs.name
@description('The web app\'s host name, for up.sh --web-origin.')
output webHostName string = web.outputs.hostName
output projectEndpoint string = foundry.outputs.projectEndpoint
output fastDeployment string = foundry.outputs.fastDeployment
output reasoningDeployment string = foundry.outputs.reasoningDeployment
