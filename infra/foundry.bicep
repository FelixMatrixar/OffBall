// Microsoft Foundry (PRD 18.9, 18.10; ADRs 0003, 0006): a Foundry resource and project, the gateway connection to
// OpenRouter (ADR 0004), the roles of whatever signs in to it (PRD 18.11) and a budget alert (OPS-4). main.bicep
// deploys it with the VM and gives the VM's managed identity its roles. On its own, for a VM outside Azure:
//
//   az group create --name offball --location <region>
//   az deployment group create --resource-group offball --template-file infra/foundry.bicep \
//     --parameters openRouterKey=<key> budgetEmails='["you@example.com"]'
//
// Only the region (the resource group's) and the OpenRouter key are required (OPS-1). The key is kept only in the
// connection. The principal IDs are the object IDs of managed identities or app registrations' service principals.

@description('Where the Foundry resource lives. Defaults to the resource group\'s region (PRD open question 2).')
param location string = resourceGroup().location

@description('The Foundry resource\'s name, which is also its subdomain, so it must be unique across Azure.')
@minLength(2)
@maxLength(64)
param name string = 'offball-${uniqueString(resourceGroup().id)}'

@description('The Foundry project the agents live in.')
param projectName string = 'offball'

@description('Your OpenRouter key (ADR 0004). Kept only in the gateway connection, never in an output.')
@secure()
param openRouterKey string

@description('OpenRouter model IDs, one per tier (PRD 14.13), the same defaults as offball/agents/llm.py.')
param fastModel string = 'openai/gpt-5-mini'
param reasoningModel string = 'openai/gpt-5'

@description('The gateway connection\'s name. Agents name a model as "<connection>/<model ID>".')
param connectionName string = 'openrouter'

@description('Object ID of what runs the crews, speech and evaluations: the VM\'s managed identity, or offball-app\'s service principal. Empty skips its roles.')
param appPrincipalId string = ''

@description('Object ID of what runs Azure MCP Server, read-only: the VM\'s managed identity, or offball-azmcp\'s service principal. Empty skips its roles.')
param azmcpPrincipalId string = ''

@description('Object ID of offball-ci\'s service principal: GitHub Actions, through workload identity federation. Empty skips its role.')
param ciPrincipalId string = ''

@description('Monthly budget for the resource group, in the subscription\'s currency.')
param budgetAmount int = 50

@description('Who hears when spending passes 50%, 80% and 100% of the budget (PRD 18.16). Empty skips the budget, as Azure for Students needs: Cost Management doesn\'t support it, and its credit is the limit.')
param budgetEmails array = []

@description('The budget\'s first month. Must be the first day of a month.')
param budgetStartDate string = '${utcNow('yyyy-MM')}-01'

var tags = {
  project: 'offball'
  purpose: 'Microsoft AI hackathon submission; all match data is synthetic'
}

// Built-in roles (PRD 18.11). Azure AI User is shown as Foundry User since the 2026 rename; its ID is unchanged.
var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  monitoringReader: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    // Microsoft Entra sign-in only: no keys exist to leak (OPS-3).
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'OffBall'
    description: 'The OffBall broadcast crew, Pundit and evaluations'
  }
}

// OpenRouter as a bring-your-own-model gateway (ADR 0004): an OpenAI-compatible Chat Completions endpoint with a
// bearer key. Whether agents resolve a model ID that itself contains a slash is part of PRD open question 13; if
// not, the crew keeps calling OpenRouter directly (PRD 14.13).
var models = [
  {
    name: fastModel
    properties: {
      model: {
        name: fastModel
        version: '1'
        format: 'OpenAI'
      }
    }
  }
  {
    name: reasoningModel
    properties: {
      model: {
        name: reasoningModel
        version: '1'
        format: 'OpenAI'
      }
    }
  }
]

resource openRouter 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: connectionName
  properties: {
    category: 'ModelGateway'
    target: 'https://openrouter.ai/api/v1'
    authType: 'ApiKey'
    isSharedToAll: false
    credentials: {
      key: openRouterKey
    }
    metadata: {
      models: string(models)
      deploymentInPath: 'false'
      authHeaderName: 'Authorization'
      authHeaderFormat: 'Bearer {api_key}'
      customHeaders: '{}'
    }
  }
}

resource appRunsAgents 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(appPrincipalId)) {
  scope: project
  name: guid(project.id, appPrincipalId, roles.foundryUser)
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource appUsesSpeech 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(appPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, appPrincipalId, roles.cognitiveServicesUser)
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
  }
}

resource azmcpReads 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(azmcpPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, azmcpPrincipalId, roles.reader)
  properties: {
    principalId: azmcpPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.reader)
  }
}

resource azmcpReadsMetrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(azmcpPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, azmcpPrincipalId, roles.monitoringReader)
  properties: {
    principalId: azmcpPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringReader)
  }
}

resource ciRunsAgents 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  scope: project
  name: guid(project.id, ciPrincipalId, roles.foundryUser)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (!empty(budgetEmails)) {
  name: 'offball-monthly'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: budgetEmails
      }
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: budgetEmails
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: budgetEmails
      }
    }
  }
}

@description('The project endpoint, which registering the agents in Foundry will use (ADR 0002).')
output projectEndpoint string = 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'
output foundryName string = foundry.name
output fastDeployment string = '${openRouter.name}/${fastModel}'
output reasoningDeployment string = '${openRouter.name}/${reasoningModel}'
