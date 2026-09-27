targetScope = 'resourceGroup'

@description('Deployment name used to make role assignment names deterministic')
#disable-next-line no-unused-params
param name string

@description('Azure region associated with the deployment')
#disable-next-line no-unused-params
param location string = resourceGroup().location

@description('Deployment tags; accepted for module consistency')
#disable-next-line no-unused-params
param tags object = {}

@description('Container registry name')
param containerRegistryName string

@description('AI Services account name')
param aiServicesAccountName string

@description('Microsoft Foundry project name')
param aiFoundryProjectName string

@description('Container App system-assigned identity principal ID')
param principalId string

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: containerRegistryName
}

resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiServicesAccountName

  resource project 'projects' existing = {
    name: aiFoundryProjectName
  }
}

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, principalId, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource azureAiUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiAccount::project.id, principalId, '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  scope: aiAccount::project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
