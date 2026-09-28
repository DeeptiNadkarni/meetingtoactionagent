targetScope = 'resourceGroup'

@description('Container app name')
param name string

@description('Azure region for the Container Apps resources')
param location string = resourceGroup().location

@description('Tags applied to the Container Apps resources')
param tags object = {}

@description('Container Apps managed environment name')
param environmentName string

@description('Name of the existing Log Analytics workspace')
param logAnalyticsWorkspaceName string

@description('Microsoft Foundry project endpoint')
param foundryProjectEndpoint string

@description('Deployed Foundry model name')
param foundryModel string

@description('Optional fine-tuned model deployment used by Model Lab')
param foundryTrainedModel string = ''

var trainedModelEnvironment = empty(foundryTrainedModel) ? [] : [
  {
    name: 'FOUNDRY_TRAINED_MODEL'
    value: foundryTrainedModel
  }
]

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2021-12-01-preview' existing = {
  name: logAnalyticsWorkspaceName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, {
    'azd-service-name': 'web'
  })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8501
        transport: 'auto'
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: 'python:3.12-slim'
          command: [
            '/bin/sh'
          ]
          args: [
            '-c'
            'if [ -f /app/app.py ]; then exec streamlit run /app/app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false; else exec python -m http.server 8501; fi'
          ]
          env: concat([
            {
              name: 'AZURE_USE_MANAGED_IDENTITY'
              value: 'true'
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL'
              value: foundryModel
            }
          ], trainedModelEnvironment)
          resources: {
            cpu: json('1')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/'
                port: 8501
                scheme: 'HTTP'
              }
              initialDelaySeconds: 1
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: 8501
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: 8501
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output environmentName string = containerAppsEnvironment.name
output name string = containerApp.name
output principalId string = containerApp.identity.principalId
output url string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
