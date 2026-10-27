// The web app's host (PRD 18.9; ADR 0007): a storage account whose static website serves web/'s build, with the
// replays, clips and posters it plays by default, over HTTPS. CI uploads the build as offball-ci, which gets
// Storage Blob Data Contributor here (.github/workflows/site.yml). Static websites are switched on in the data
// plane, which Bicep can't reach, so deploy/README.md runs that once. main.bicep deploys it with the VM and Foundry.

@description('Where the web app is served from. It must be a region the subscription allows.')
param location string = resourceGroup().location

@description('The storage account\'s name: 3 to 24 lowercase letters and digits, unique across Azure.')
@minLength(3)
@maxLength(24)
param name string = 'offballweb${uniqueString(resourceGroup().id)}'

@description('Object ID of offball-ci\'s service principal, which uploads the build. Empty skips its role.')
param ciPrincipalId string = ''

var tags = {
  project: 'offball'
  purpose: 'Microsoft AI hackathon submission; all match data is synthetic'
}

// Storage Blob Data Contributor: write and delete blobs, here only the website's.
var blobWriter = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource web 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    // The website stays public through its own endpoint; no container is.
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

resource ciUploads 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  scope: web
  name: guid(web.id, ciPrincipalId, blobWriter)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobWriter)
  }
}

output name string = web.name
@description('The web app\'s host name, for up.sh --web-origin.')
output hostName string = replace(replace(web.properties.primaryEndpoints.web, 'https://', ''), '/', '')
