targetScope = 'resourceGroup'

@description('Container registry name')
param name string

@description('Azure region for the registry')
param location string = resourceGroup().location

@description('Tags applied to the registry')
param tags object = {}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output id string = registry.id
output loginServer string = registry.properties.loginServer
output name string = registry.name
