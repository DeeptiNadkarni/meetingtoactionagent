targetScope = 'resourceGroup'

@description('Logic App name')
param name string

@description('Azure region for the recovery workflow')
param location string = resourceGroup().location

@description('Tags applied to the recovery workflow')
param tags object = {}

@description('Existing AI Services account name')
param aiServicesAccountName string

@description('DeveloperTier deployment name')
param deploymentName string

@description('Fine-tuned model artifact name')
param modelName string

@description('Fine-tuned model artifact version')
param modelVersion string = '1'

@minValue(5)
@maxValue(60)
@description('Minutes between deployment checks')
param checkIntervalMinutes int = 15

var deploymentApiVersion = '2025-06-01'
var resourceManagerEndpoint = environment().resourceManager
var deploymentUri = '${resourceManagerEndpoint}${aiAccount.id}/deployments/${deploymentName}?api-version=${deploymentApiVersion}'
var workflowSchema = 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
var openAiContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'

resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiServicesAccountName
}

resource recoveryWorkflow 'Microsoft.Logic/workflows@2019-05-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': workflowSchema
      contentVersion: '1.0.0.0'
      triggers: {
        Check_every_15_minutes: {
          type: 'Recurrence'
          recurrence: {
            frequency: 'Minute'
            interval: checkIntervalMinutes
          }
        }
      }
      actions: {
        Check_deployment: {
          type: 'Http'
          inputs: {
            method: 'GET'
            uri: deploymentUri
            authentication: {
              type: 'ManagedServiceIdentity'
              audience: resourceManagerEndpoint
            }
            retryPolicy: {
              type: 'none'
            }
          }
          runAfter: {}
        }
        Recreate_deployment: {
          type: 'Http'
          inputs: {
            method: 'PUT'
            uri: deploymentUri
            headers: {
              'Content-Type': 'application/json'
            }
            body: {
              sku: {
                name: 'DeveloperTier'
                capacity: 50
              }
              properties: {
                model: {
                  format: 'OpenAI'
                  name: modelName
                  version: modelVersion
                }
              }
            }
            authentication: {
              type: 'ManagedServiceIdentity'
              audience: resourceManagerEndpoint
            }
            retryPolicy: {
              type: 'fixed'
              count: 3
              interval: 'PT20S'
            }
          }
          runAfter: {
            Check_deployment: [
              'Failed'
            ]
          }
        }
        Verify_deployment: {
          type: 'Http'
          inputs: {
            method: 'GET'
            uri: deploymentUri
            authentication: {
              type: 'ManagedServiceIdentity'
              audience: resourceManagerEndpoint
            }
            retryPolicy: {
              type: 'fixed'
              count: 6
              interval: 'PT30S'
            }
          }
          runAfter: {
            Recreate_deployment: [
              'Succeeded'
            ]
          }
        }
      }
      outputs: {}
    }
    parameters: {}
  }
}

resource recoveryRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiAccount.id, name, openAiContributorRoleId)
  scope: aiAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiContributorRoleId)
    principalId: recoveryWorkflow.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output name string = recoveryWorkflow.name
output principalId string = recoveryWorkflow.identity.principalId