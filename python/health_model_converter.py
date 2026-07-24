#!/usr/bin/env python3
"""
Azure Health Model Converter - Python Implementation
Converts V1 Health Models to V2 Bicep format
"""

import argparse
import json
import hashlib
import logging
import os
import sys
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime

# Azure SDK imports (optional - for Azure resource conversion)
try:
    from azure.identity import DefaultAzureCredential
    from azure.core.credentials import AccessToken
    import requests
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False

# ============================================================================
# Constants
# ============================================================================

SUPPORTED_V2_LOCATIONS = ["canadacentral", "uksouth"]
PROVIDER_NAMESPACE = "Microsoft.CloudHealth"
HEALTH_MODELS_RESOURCE_TYPE = "healthmodels"
API_VERSION = "2026-05-01-preview"

# ============================================================================
# Utility Functions
# ============================================================================

def generate_deterministic_guid(input_string: str) -> str:
    """Generate a deterministic GUID from an input string."""
    input_bytes = input_string.encode('utf-8')
    hash_bytes = hashlib.sha256(input_bytes).digest()
    # Take first 16 bytes for GUID
    guid_bytes = hash_bytes[:16]
    # Format as GUID string
    return f"{guid_bytes[:4].hex()}-{guid_bytes[4:6].hex()}-{guid_bytes[6:8].hex()}-{guid_bytes[8:10].hex()}-{guid_bytes[10:16].hex()}"

def setup_logger(name: str = "HealthModelConverter") -> logging.Logger:
    """Setup and return a logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger

# ============================================================================
# V1 Model Classes (Input)
# ============================================================================

@dataclass
class V1Query:
    queryType: str
    queryId: str
    degradedThreshold: str
    degradedOperator: str
    unhealthyThreshold: str
    unhealthyOperator: str
    timeGrain: str
    dataUnit: str
    enabledState: str
    name: str = ""
    queryText: str = ""
    valueColumnName: Optional[str] = None
    dataType: str = ""
    metricName: str = ""
    metricNamespace: str = ""
    aggregationType: str = ""
    dimension: Optional[str] = None
    dimensionFilter: Optional[str] = None

@dataclass
class V1Visual:
    x: int
    y: int

@dataclass
class V1Node:
    nodeType: str
    nodeId: str
    name: str
    childNodeIds: Optional[List[str]]
    visual: Optional[V1Visual]
    impact: str
    azureResourceId: str
    credentialId: str
    queries: Optional[List[V1Query]]
    nodeKind: str
    logAnalyticsResourceId: str = ""
    logAnalyticsWorkspaceId: str = ""
    azureMonitorWorkspaceResourceId: str = ""
    queryEndpoint: str = ""

@dataclass
class V1Properties:
    versionNumber: str
    activeState: str
    refreshInterval: str
    provisioningState: str
    nodes: Optional[List[V1Node]]

@dataclass
class V1UserAssignedIdentity:
    principalId: str
    clientId: str

@dataclass
class V1Identity:
    principalId: str
    tenantId: str
    type: str
    userAssignedIdentities: Optional[Dict[str, V1UserAssignedIdentity]]

@dataclass
class V1SystemData:
    createdBy: str
    createdByType: str
    createdAt: str
    lastModifiedBy: str
    lastModifiedByType: str
    lastModifiedAt: str

@dataclass
class V1HealthModel:
    id: str
    name: str
    type: str
    location: str
    tags: Optional[Dict[str, str]]
    systemData: Optional[V1SystemData]
    identity: Optional[V1Identity]
    properties: V1Properties

# ============================================================================
# V2 Model Classes & Bicep Generation
# ============================================================================

class BicepBuilder:
    """Helper class to build Bicep templates."""
    
    @staticmethod
    def format_tags(tags: Optional[Dict[str, str]]) -> str:
        """Format tags for Bicep."""
        if not tags:
            return "null"
        items = [f"    {k}: '{v}'" for k, v in tags.items()]
        return "{\n" + "\n".join(items) + "\n  }"
    
    @staticmethod
    def format_depends_on(depends_on: Optional[List[str]]) -> str:
        """Format dependsOn array for Bicep."""
        if not depends_on:
            return "[]"
        items = ["    " + item for item in depends_on]
        return "[\n" + "\n".join(items) + "\n  ]"
    
    @staticmethod
    def format_identity(identity_type: str, user_assigned: Optional[Dict[str, Any]]) -> str:
        """Format identity object for Bicep."""
        user_mi = "null"
        if user_assigned:
            items = [f"      '{k}': {{}}" for k in user_assigned.keys()]
            user_mi = "{\n" + "\n".join(items) + "\n    }"
        
        return f"""{{
    type: '{identity_type}'
    userAssignedIdentities: {user_mi}
  }}"""

    @staticmethod
    def format_evaluation_rules(unhealthy_operator: str, unhealthy_threshold: str,
                                degraded_operator: str, degraded_threshold: str) -> str:
        """Format evaluation rules for Bicep."""
        degraded_str = ""
        if degraded_operator and degraded_threshold:
            degraded_str = f"""
                    degradedRule: {{
                      operator: '{degraded_operator}'
                      threshold: {degraded_threshold}
                    }}"""

        return f"""{{
                    unhealthyRule: {{
                      operator: '{unhealthy_operator}'
                      threshold: {unhealthy_threshold}
                    }}{degraded_str}
                  }}"""

class V2HealthModel:
    """V2 Health Model resource."""
    
    def __init__(self, name: str, location: str, identity: Optional[V1Identity], tags: Optional[Dict[str, str]]):
        self.name = name
        self.location = location
        self.tags = tags
        self.identity = identity
        self.type = f"{PROVIDER_NAMESPACE}/{HEALTH_MODELS_RESOURCE_TYPE}"
        self.api_version = API_VERSION
    
    def to_bicep(self, symbolic_name: str, resource_name_param: str) -> str:
        """Generate Bicep representation."""
        location_str = "location"  # Always use the parameter reference
        identity_str = "null"
        
        if self.identity:
            user_assigned = {}
            if self.identity.userAssignedIdentities:
                user_assigned = {k: {} for k in self.identity.userAssignedIdentities.keys()}
            identity_str = BicepBuilder.format_identity(self.identity.type, user_assigned)
        
        tags_str = BicepBuilder.format_tags(self.tags)
        
        return f"""resource {symbolic_name} '{self.type}@{self.api_version}' = {{
  name: {resource_name_param}
  location: {location_str}
  identity: {identity_str}
  tags: {tags_str}
  properties: {{}}
  dependsOn: []
}}"""

class AuthenticationSetting:
    """Authentication setting resource."""
    
    def __init__(self, name: str, display_name: str, managed_identity_name: str):
        self.name = name
        self.display_name = display_name
        self.managed_identity_name = managed_identity_name
        self.type = f"{PROVIDER_NAMESPACE}/{HEALTH_MODELS_RESOURCE_TYPE}/authenticationSettings"
        self.api_version = API_VERSION
    
    def to_bicep(self, symbolic_name: str, parent: str) -> str:
        """Generate Bicep representation."""
        return f"""resource {symbolic_name} '{self.type}@{self.api_version}' = {{
  parent: {parent}
  name: '{self.name}'
  properties: {{
    displayName: '{self.display_name}'
    authenticationKind: 'ManagedIdentity'
    managedIdentityName: '{self.managed_identity_name}'
  }}
  dependsOn: []
}}"""

class Entity:
    """Entity resource."""
    
    def __init__(self, name: str, display_name: str, impact: str, canvas_position: Optional[Tuple[int, int]]):
        self.name = name
        self.display_name = display_name
        self.impact = impact
        self.canvas_position = canvas_position
        self.type = f"{PROVIDER_NAMESPACE}/{HEALTH_MODELS_RESOURCE_TYPE}/entities"
        self.api_version = API_VERSION
        self.signal_groups = {}
    
    def add_azure_resource_signals(self, resource_id: str, auth_setting_symbolic: str, signals: List[dict]):
        """Add Azure Resource Metric signal group with inline signal instances."""
        self.signal_groups['azureResource'] = {
            'resource_id': resource_id,
            'auth_setting_symbolic': auth_setting_symbolic,
            'signals': signals
        }
    
    def add_log_analytics_signals(self, workspace_id: str, auth_setting_symbolic: str, signals: List[dict]):
        """Add Log Analytics signal group with inline signal instances."""
        self.signal_groups['azureLogAnalytics'] = {
            'resource_id': workspace_id,
            'auth_setting_symbolic': auth_setting_symbolic,
            'signals': signals
        }
    
    def add_prometheus_signals(self, workspace_id: str, auth_setting_symbolic: str, signals: List[dict]):
        """Add Azure Monitor Workspace signal group with inline signal instances."""
        self.signal_groups['azureMonitorWorkspace'] = {
            'resource_id': workspace_id,
            'auth_setting_symbolic': auth_setting_symbolic,
            'signals': signals
        }
    
    def to_bicep(self, symbolic_name: str, parent: str, depends_on: Optional[List[str]] = None,
                 overwrite_name_param: Optional[str] = None) -> str:
        """Generate Bicep representation."""
        name_str = overwrite_name_param if overwrite_name_param else f"'{self.name}'"
        canvas_str = "null"
        if self.canvas_position:
            canvas_str = f"""{{
      x: {self.canvas_position[0]}
      y: {self.canvas_position[1]}
    }}"""
        
        signal_groups_str = self._build_signal_groups_string()
        depends_str = BicepBuilder.format_depends_on(depends_on)
        
        return f"""resource {symbolic_name} '{self.type}@{self.api_version}' = {{
  parent: {parent}
  name: {name_str}
  properties: {{
    displayName: '{self.display_name}'
    impact: '{self.impact}'
    canvasPosition: {canvas_str}
    signalGroups: {signal_groups_str}
  }}
  dependsOn: {depends_str}
}}"""
    
    def _build_signal_groups_string(self) -> str:
        """Build the signalGroups section of the entity."""
        if not self.signal_groups:
            return "null"
        
        parts = []
        
        # Azure Resource signals
        if 'azureResource' in self.signal_groups:
            group = self.signal_groups['azureResource']
            signals_str = self._build_signals_array(group['signals'])
            parts.append(f"""    azureResource: {{
      azureResourceId: '{group['resource_id']}'
      authenticationSetting: {group['auth_setting_symbolic']}.name
      signals: {signals_str}
    }}""")
        else:
            parts.append("    azureResource: null")
        
        # Log Analytics signals
        if 'azureLogAnalytics' in self.signal_groups:
            group = self.signal_groups['azureLogAnalytics']
            signals_str = self._build_signals_array(group['signals'])
            parts.append(f"""    azureLogAnalytics: {{
      logAnalyticsWorkspaceResourceId: '{group['resource_id']}'
      authenticationSetting: {group['auth_setting_symbolic']}.name
      signals: {signals_str}
    }}""")
        else:
            parts.append("    azureLogAnalytics: null")
        
        # Azure Monitor Workspace signals
        if 'azureMonitorWorkspace' in self.signal_groups:
            group = self.signal_groups['azureMonitorWorkspace']
            signals_str = self._build_signals_array(group['signals'])
            parts.append(f"""    azureMonitorWorkspace: {{
      azureMonitorWorkspaceResourceId: '{group['resource_id']}'
      authenticationSetting: {group['auth_setting_symbolic']}.name
      signals: {signals_str}
    }}""")
        else:
            parts.append("    azureMonitorWorkspace: null")
        
        return "{\n" + "\n".join(parts) + "\n  }"
    
    def _build_signals_array(self, signals: List[dict]) -> str:
        """Build inline signals array."""
        if not signals:
            return "null"
        
        items = []
        for sig in signals:
            items.append(sig['bicep'])
        
        return "[\n" + "\n".join(items) + "\n      ]"

def build_azure_resource_signal_bicep(query: 'V1Query') -> str:
    """Build Bicep string for an Azure Resource Metric signal instance."""
    dimension_str = "null" if not query.dimension else f"'{query.dimension}'"
    dimension_filter_str = "null" if not query.dimensionFilter else f"'{query.dimensionFilter}'"
    data_unit_str = "null" if not query.dataUnit else f"'{query.dataUnit}'"
    eval_rules = BicepBuilder.format_evaluation_rules(
        query.unhealthyOperator, query.unhealthyThreshold,
        query.degradedOperator, query.degradedThreshold)
    
    return f"""        {{
          signalKind: 'AzureResourceMetric'
          name: '{query.queryId}'
          displayName: '{query.metricName}'
          dataUnit: {data_unit_str}
          metricNamespace: '{query.metricNamespace}'
          metricName: '{query.metricName}'
          timeGrain: '{query.timeGrain}'
          refreshInterval: 'PT1M'
          aggregationType: '{query.aggregationType}'
          dimension: {dimension_str}
          dimensionFilter: {dimension_filter_str}
          evaluationRules: {eval_rules}
        }}"""

def build_log_analytics_signal_bicep(query: 'V1Query') -> str:
    """Build Bicep string for a Log Analytics signal instance."""
    query_text = query.queryText.replace('\n', '\\n')
    value_column = "null" if not query.valueColumnName else f"'{query.valueColumnName}'"
    time_grain = "null" if not query.timeGrain else f"'{query.timeGrain}'"
    data_unit = "null" if not query.dataUnit else f"'{query.dataUnit}'"
    eval_rules = BicepBuilder.format_evaluation_rules(
        query.unhealthyOperator, query.unhealthyThreshold,
        query.degradedOperator, query.degradedThreshold)
    
    return f"""        {{
          signalKind: 'LogAnalyticsQuery'
          name: '{query.queryId}'
          displayName: '{query.name}'
          dataUnit: {data_unit}
          queryText: '{query_text}'
          valueColumnName: {value_column}
          timeGrain: {time_grain}
          refreshInterval: 'PT1M'
          evaluationRules: {eval_rules}
        }}"""

def build_prometheus_signal_bicep(query: 'V1Query') -> str:
    """Build Bicep string for a Prometheus Metrics signal instance."""
    query_text = query.queryText.replace('\n', '\\n')
    time_grain = "null" if not query.timeGrain else f"'{query.timeGrain}'"
    data_unit = "null" if not query.dataUnit else f"'{query.dataUnit}'"
    eval_rules = BicepBuilder.format_evaluation_rules(
        query.unhealthyOperator, query.unhealthyThreshold,
        query.degradedOperator, query.degradedThreshold)
    
    return f"""        {{
          signalKind: 'PrometheusMetricsQuery'
          name: '{query.queryId}'
          displayName: '{query.name}'
          dataUnit: {data_unit}
          queryText: '{query_text}'
          timeGrain: {time_grain}
          refreshInterval: 'PT1M'
          evaluationRules: {eval_rules}
        }}"""

class Relationship:
    """Relationship resource."""
    
    def __init__(self, name: str, parent_entity: str, child_entity: str,
                 parent_entity_symbolic: str, child_entity_symbolic: str):
        self.name = name
        self.parent_entity = parent_entity
        self.child_entity = child_entity
        self.parent_entity_symbolic = parent_entity_symbolic
        self.child_entity_symbolic = child_entity_symbolic
        self.type = f"{PROVIDER_NAMESPACE}/{HEALTH_MODELS_RESOURCE_TYPE}/relationships"
        self.api_version = API_VERSION
    
    def to_bicep(self, symbolic_name: str, parent: str) -> str:
        """Generate Bicep representation."""
        return f"""resource {symbolic_name} '{self.type}@{self.api_version}' = {{
  parent: {parent}
  name: '{self.name}'
  properties: {{
    parentEntityName: {self.parent_entity_symbolic}.name
    childEntityName: {self.child_entity_symbolic}.name
  }}
}}"""

# ============================================================================
# Azure Resource Utilities
# ============================================================================

def validate_resource_id(resource_id: str) -> bool:
    """Validate Azure resource ID format."""
    # Basic pattern for Azure resource IDs
    pattern = r'^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/[^/]+/.+$'
    return bool(re.match(pattern, resource_id, re.IGNORECASE))

def parse_resource_id(resource_id: str) -> Dict[str, str]:
    """Parse Azure resource ID into components."""
    parts = resource_id.strip('/').split('/')
    result = {}
    
    for i in range(0, len(parts), 2):
        if i + 1 < len(parts):
            key = parts[i].lower()
            value = parts[i + 1]
            result[key] = value
    
    return result

# ============================================================================
# Conversion Logic
# ============================================================================

class HealthModelConverter:
    """Main converter class."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def convert_v1_to_v2_bicep(self, v1_model: V1HealthModel) -> Optional[str]:
        """Convert V1 health model to V2 Bicep format."""
        try:
            # Validate and set location
            location = v1_model.location.lower()
            if location not in SUPPORTED_V2_LOCATIONS:
                self.logger.warning(f"Location '{location}' is not supported in V2. Falling back to '{SUPPORTED_V2_LOCATIONS[0]}'")
                location = SUPPORTED_V2_LOCATIONS[0]
            
            # Initialize Bicep builder
            bicep_lines = []
            resource_name_param = "resourceName"
            
            # Add parameters
            bicep_lines.append(f"param {resource_name_param} string = '{v1_model.name}'")
            bicep_lines.append(f"param location string = '{location}'")
            bicep_lines.append("")
            
            # Create V2 health model
            model_symbolic_name = "healthModel"
            v2_model = V2HealthModel(v1_model.name, location, v1_model.identity, v1_model.tags)
            bicep_lines.append(v2_model.to_bicep(model_symbolic_name, resource_name_param))
            bicep_lines.append("")
            
            # Check for nodes
            if not v1_model.properties.nodes:
                self.logger.warning("No nodes found in v1 health model")
                return None
            
            # Track resources
            authentication_settings = {}
            entities = {}
            relationships = {}
            
            # Create authentication settings
            if v1_model.identity:
                # System assigned identity
                if "SystemAssigned" in v1_model.identity.type:
                    auth_setting = AuthenticationSetting("SystemAssigned", "SystemAssigned", "SystemAssigned")
                    symbolic_name = "authenticationSettingSystemAssigned"
                    authentication_settings[symbolic_name] = auth_setting
                    bicep_lines.append("")
                    bicep_lines.append(auth_setting.to_bicep(symbolic_name, model_symbolic_name))
                
                # User assigned identities
                if v1_model.identity.userAssignedIdentities:
                    for idx, (user_mi_key, _) in enumerate(v1_model.identity.userAssignedIdentities.items()):
                        user_mi_name = user_mi_key.split('/')[-1]
                        guid_name = generate_deterministic_guid(user_mi_key)
                        auth_setting = AuthenticationSetting(guid_name, user_mi_name, user_mi_key)
                        symbolic_name = f"authenticationSettingUserMi{len(authentication_settings)}"
                        authentication_settings[symbolic_name] = auth_setting
                        bicep_lines.append("")
                        bicep_lines.append(auth_setting.to_bicep(symbolic_name, model_symbolic_name))
            
            # Process entities (nodes) with inline signals
            for node in v1_model.properties.nodes:
                # Check if this is the root node
                is_root = node.nodeId == "0"
                node_name = v1_model.name if is_root else node.nodeId
                
                # Create entity
                canvas_pos = None
                if node.visual:
                    canvas_pos = (node.visual.x, node.visual.y)
                
                entity = Entity(node_name, node.name, node.impact, canvas_pos)
                
                depends_on = []
                
                # Process queries for this entity
                if node.queries:
                    enabled_queries = [q for q in node.queries if q.enabledState == "Enabled"]
                    
                    if enabled_queries:
                        # Find authentication setting
                        auth_setting_key = None
                        for key, auth in authentication_settings.items():
                            if auth.managed_identity_name.lower().endswith(node.credentialId.lower()):
                                auth_setting_key = key
                                break
                        
                        if not auth_setting_key and authentication_settings:
                            # Use first available auth setting as fallback
                            auth_setting_key = list(authentication_settings.keys())[0]
                            self.logger.warning(f"Using default authentication setting for entity {node_name}")
                        
                        if auth_setting_key:
                            auth_setting = authentication_settings[auth_setting_key]
                            
                            # Group queries by type
                            resource_metrics = [q for q in enabled_queries 
                                               if q.queryType == "ResourceMetricsQuery" and 
                                               q.metricNamespace.lower() != "microsoft.healthmodel/healthmodels" and
                                               q.dataType != "Text"]
                            log_analytics = [q for q in enabled_queries 
                                           if q.queryType == "LogQuery" and q.dataType != "Text"]
                            prometheus = [q for q in enabled_queries 
                                        if q.queryType == "PrometheusMetricsQuery"]
                            
                            # Add Azure Resource signal group with inline signals
                            if resource_metrics:
                                azure_resource_id = node.azureResourceId
                                # Handle nested health models
                                if "microsoft.healthmodel/healthmodels" in azure_resource_id.lower():
                                    azure_resource_id = azure_resource_id.replace(
                                        "microsoft.healthmodel/healthmodels",
                                        "Microsoft.CloudHealth/healthmodels"
                                    )
                                    self.logger.info(f"Replacing resource provider for nested health model {node_name}")
                                
                                signals = [{'bicep': build_azure_resource_signal_bicep(q)} for q in resource_metrics]
                                entity.add_azure_resource_signals(
                                    azure_resource_id,
                                    auth_setting_key,
                                    signals
                                )
                            
                            # Add Log Analytics signal group with inline signals
                            if log_analytics and node.logAnalyticsResourceId:
                                signals = [{'bicep': build_log_analytics_signal_bicep(q)} for q in log_analytics]
                                entity.add_log_analytics_signals(
                                    node.logAnalyticsResourceId,
                                    auth_setting_key,
                                    signals
                                )
                            
                            # Add Prometheus signal group with inline signals
                            if prometheus and node.azureMonitorWorkspaceResourceId:
                                signals = [{'bicep': build_prometheus_signal_bicep(q)} for q in prometheus]
                                entity.add_prometheus_signals(
                                    node.azureMonitorWorkspaceResourceId,
                                    auth_setting_key,
                                    signals
                                )
                
                # Add entity to collection
                symbolic_name = f"entity{len(entities)}"
                entities[symbolic_name] = entity
                
                bicep_lines.append("")
                if is_root:
                    bicep_lines.append(entity.to_bicep(
                        symbolic_name, model_symbolic_name, depends_on, resource_name_param
                    ))
                else:
                    bicep_lines.append(entity.to_bicep(
                        symbolic_name, model_symbolic_name, depends_on
                    ))
            
            # Process relationships
            for node in v1_model.properties.nodes:
                node_name = v1_model.name if node.nodeId == "0" else node.nodeId
                
                if node.childNodeIds:
                    for child_id in node.childNodeIds:
                        # Find parent and child entity symbolic names
                        parent_entity_key = None
                        child_entity_key = None
                        
                        for key, entity in entities.items():
                            if entity.name == node_name:
                                parent_entity_key = key
                            if entity.name == child_id:
                                child_entity_key = key
                        
                        relationship_name = generate_deterministic_guid(f"{node_name}-{child_id}")
                        relationship = Relationship(
                            relationship_name, node_name, child_id,
                            parent_entity_key or "entity0",
                            child_entity_key or "entity0"
                        )
                        
                        symbolic_name = f"relationship{len(relationships)}"
                        relationships[symbolic_name] = relationship
                        
                        bicep_lines.append("")
                        bicep_lines.append(relationship.to_bicep(
                            symbolic_name, model_symbolic_name
                        ))
            
            return "\n".join(bicep_lines)
            
        except Exception as e:
            self.logger.error(f"Failed to convert v1 health model '{v1_model.name}' to v2 Bicep: {str(e)}")
            return None
    
    def load_v1_model(self, file_path: str) -> Optional[V1HealthModel]:
        """Load V1 health model from JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Parse the JSON into V1 model structure
            return self._parse_v1_model(data)
            
        except Exception as e:
            self.logger.error(f"Failed to load V1 model from '{file_path}': {str(e)}")
            return None
    
    def _parse_v1_model(self, data: Dict[str, Any]) -> V1HealthModel:
        """Parse JSON data into V1HealthModel."""
        # Parse identity if present
        identity = None
        if 'identity' in data and data['identity']:
            user_assigned = None
            if 'userAssignedIdentities' in data['identity'] and data['identity']['userAssignedIdentities']:
                user_assigned = {}
                for key, value in data['identity']['userAssignedIdentities'].items():
                    user_assigned[key] = V1UserAssignedIdentity(
                        value.get('principalId', ''),
                        value.get('clientId', '')
                    )
            
            identity = V1Identity(
                data['identity'].get('principalId', ''),
                data['identity'].get('tenantId', ''),
                data['identity'].get('type', ''),
                user_assigned
            )
        
        # Parse nodes
        nodes = None
        if 'properties' in data and 'nodes' in data['properties'] and data['properties']['nodes']:
            nodes = []
            for node_data in data['properties']['nodes']:
                # Parse visual
                visual = None
                if 'visual' in node_data and node_data['visual']:
                    visual = V1Visual(
                        node_data['visual'].get('x', 0),
                        node_data['visual'].get('y', 0)
                    )
                
                # Parse queries
                queries = None
                if 'queries' in node_data and node_data['queries']:
                    queries = []
                    for query_data in node_data['queries']:
                        query = V1Query(
                            queryType=query_data.get('queryType', ''),
                            queryId=query_data.get('queryId', ''),
                            degradedThreshold=query_data.get('degradedThreshold', ''),
                            degradedOperator=query_data.get('degradedOperator', ''),
                            unhealthyThreshold=query_data.get('unhealthyThreshold', ''),
                            unhealthyOperator=query_data.get('unhealthyOperator', ''),
                            timeGrain=query_data.get('timeGrain', ''),
                            dataUnit=query_data.get('dataUnit', ''),
                            enabledState=query_data.get('enabledState', ''),
                            name=query_data.get('name', ''),
                            queryText=query_data.get('queryText', ''),
                            valueColumnName=query_data.get('valueColumnName'),
                            dataType=query_data.get('dataType', ''),
                            metricName=query_data.get('metricName', ''),
                            metricNamespace=query_data.get('metricNamespace', ''),
                            aggregationType=query_data.get('aggregationType', ''),
                            dimension=query_data.get('dimension'),
                            dimensionFilter=query_data.get('dimensionFilter')
                        )
                        queries.append(query)
                
                node = V1Node(
                    nodeType=node_data.get('nodeType', ''),
                    nodeId=node_data.get('nodeId', ''),
                    name=node_data.get('name', ''),
                    childNodeIds=node_data.get('childNodeIds'),
                    visual=visual,
                    impact=node_data.get('impact', ''),
                    azureResourceId=node_data.get('azureResourceId', ''),
                    credentialId=node_data.get('credentialId', ''),
                    queries=queries,
                    nodeKind=node_data.get('nodeKind', ''),
                    logAnalyticsResourceId=node_data.get('logAnalyticsResourceId', ''),
                    logAnalyticsWorkspaceId=node_data.get('logAnalyticsWorkspaceId', ''),
                    azureMonitorWorkspaceResourceId=node_data.get('azureMonitorWorkspaceResourceId', ''),
                    queryEndpoint=node_data.get('queryEndpoint', '')
                )
                nodes.append(node)
        
        # Parse properties
        properties = V1Properties(
            versionNumber=data['properties'].get('versionNumber', ''),
            activeState=data['properties'].get('activeState', ''),
            refreshInterval=data['properties'].get('refreshInterval', ''),
            provisioningState=data['properties'].get('provisioningState', ''),
            nodes=nodes
        )
        
        # Parse system data if present
        system_data = None
        if 'systemData' in data and data['systemData']:
            system_data = V1SystemData(
                createdBy=data['systemData'].get('createdBy', ''),
                createdByType=data['systemData'].get('createdByType', ''),
                createdAt=data['systemData'].get('createdAt', ''),
                lastModifiedBy=data['systemData'].get('lastModifiedBy', ''),
                lastModifiedByType=data['systemData'].get('lastModifiedByType', ''),
                lastModifiedAt=data['systemData'].get('lastModifiedAt', '')
            )
        
        # Create V1HealthModel
        return V1HealthModel(
            id=data.get('id', ''),
            name=data.get('name', ''),
            type=data.get('type', ''),
            location=data.get('location', ''),
            tags=data.get('tags'),
            systemData=system_data,
            identity=identity,
            properties=properties
        )
    
    def write_output_file(self, content: str, output_folder: str, model_name: str, extension: str = ".bicep") -> bool:
        """Write content to file with specified extension."""
        try:
            # Create output directory if it doesn't exist
            Path(output_folder).mkdir(parents=True, exist_ok=True)
            
            # Generate output file path
            output_file = Path(output_folder) / f"{model_name}{extension}"
            
            # Write the file
            self.logger.info(f"Writing result to output file '{output_file}'...")
            with open(output_file, 'w') as f:
                f.write(content)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to write output file: {str(e)}")
            return False
    
    def check_bicep_availability(self) -> bool:
        """Check if az bicep build command is available."""
        try:
            # Check if az CLI is installed
            result = subprocess.run(["az", "--version"], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                self.logger.error("Azure CLI is not installed or not in PATH")
                return False
            
            # Check if bicep is available
            result = subprocess.run(["az", "bicep", "version"], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                self.logger.error("Bicep is not installed. Please run: az bicep install")
                return False
            
            self.logger.debug(f"Bicep version: {result.stdout.strip()}")
            return True
            
        except FileNotFoundError:
            self.logger.error("Azure CLI is not installed or not in PATH")
            return False
        except Exception as e:
            self.logger.error(f"Error checking Bicep availability: {str(e)}")
            return False
    
    def compile_bicep_to_arm(self, bicep_content: str, model_name: str) -> Optional[str]:
        """Compile Bicep content to ARM template using az bicep build."""
        try:
            # Create temporary Bicep file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.bicep', delete=False) as temp_bicep:
                temp_bicep.write(bicep_content)
                temp_bicep_path = temp_bicep.name
            
            # Create temporary output file path
            temp_arm_path = temp_bicep_path.replace('.bicep', '.json')
            
            try:
                # Compile Bicep to ARM template
                self.logger.info(f"Compiling Bicep to ARM template for '{model_name}'...")
                result = subprocess.run(
                    ["az", "bicep", "build", "--file", temp_bicep_path, "--outfile", temp_arm_path],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode != 0:
                    self.logger.error(f"Failed to compile Bicep to ARM template: {result.stderr}")
                    return None
                
                # Read the compiled ARM template
                with open(temp_arm_path, 'r') as f:
                    arm_content = f.read()
                
                return arm_content
                
            finally:
                # Clean up temporary files
                try:
                    os.unlink(temp_bicep_path)
                    if os.path.exists(temp_arm_path):
                        os.unlink(temp_arm_path)
                except:
                    pass
                    
        except Exception as e:
            self.logger.error(f"Failed to compile Bicep to ARM template: {str(e)}")
            return None
    
    def fetch_from_azure(self, resource_id: str) -> Optional[V1HealthModel]:
        """Fetch V1 health model from Azure using resource ID."""
        if not AZURE_SDK_AVAILABLE:
            self.logger.error("Azure SDK is not installed. Please install: pip install azure-identity requests")
            return None
        
        try:
            # Validate resource ID
            if not validate_resource_id(resource_id):
                self.logger.error(f"Invalid resource ID format: {resource_id}")
                return None
            
            # Get Azure credentials
            self.logger.info("Getting access token for ARM...")
            credential = DefaultAzureCredential()
            token = credential.get_token("https://management.azure.com/.default")
            
            # Construct URL for the health model resource
            url = f"https://management.azure.com{resource_id}?api-version=2022-11-01-preview"
            
            # Set up headers with authentication
            headers = {
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json"
            }
            
            # Make the request
            self.logger.info(f"Getting resource {resource_id}...")
            response = requests.get(url, headers=headers)
            
            if not response.ok:
                self.logger.error(f"Failed to get resource {resource_id}")
                self.logger.error(f"Status code: {response.status_code}")
                self.logger.error(f"Response: {response.text}")
                return None
            
            # Parse the response
            data = response.json()
            
            # Convert to V1HealthModel
            v1_model = self._parse_v1_model(data)
            self.logger.info(f"Health model '{v1_model.name}' retrieved from ARM")
            
            return v1_model
            
        except Exception as e:
            self.logger.error(f"Failed to fetch health model from Azure: {str(e)}")
            if "DefaultAzureCredential" in str(e):
                self.logger.error("Authentication failed. Please ensure you are logged in to Azure (e.g., 'az login')")
            return None

# ============================================================================
# Main CLI Application
# ============================================================================

def main():
    """Main entry point for the CLI application."""
    parser = argparse.ArgumentParser(
        description='Convert Azure Health Models from V1 to V2 Bicep format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s convert file -i model.json -o ./output
  %(prog)s convert file --inputfile model.json --outputfolder ./output
  %(prog)s convert file -i model.json -o ./output --armtemplate
  %(prog)s convert azure -r "/subscriptions/.../providers/Microsoft.HealthModel/healthmodels/mymodel" -o ./output
  %(prog)s convert azure -r "/subscriptions/.../providers/Microsoft.HealthModel/healthmodels/mymodel" -o ./output --armtemplate
  
Azure authentication:
  For Azure conversion, ensure you are authenticated using one of:
  - Azure CLI: az login
  - Environment variables for service principal
  - Managed identity (when running in Azure)
  
Required packages for Azure conversion:
  pip install azure-identity requests
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Convert command
    convert_parser = subparsers.add_parser('convert', help='Convert health models')
    convert_subparsers = convert_parser.add_subparsers(dest='source', help='Source of health model')
    
    # File-based conversion
    file_parser = convert_subparsers.add_parser('file', help='Convert from JSON file')
    file_parser.add_argument(
        '-i', '--inputfile',
        required=True,
        help='Path to input JSON file containing V1 health model'
    )
    file_parser.add_argument(
        '-o', '--outputfolder',
        required=True,
        help='Output folder path for generated Bicep file'
    )
    file_parser.add_argument(
        '--armtemplate',
        action='store_true',
        help='Compile the Bicep output to ARM template JSON (requires az bicep)'
    )
    
    # Azure-based conversion
    azure_parser = convert_subparsers.add_parser('azure', help='Convert from Azure resource')
    azure_parser.add_argument(
        '-r', '--resource-id',
        required=True,
        help='Azure resource ID of the health model'
    )
    azure_parser.add_argument(
        '-o', '--outputfolder',
        required=True,
        help='Output folder path for generated Bicep file'
    )
    azure_parser.add_argument(
        '--armtemplate',
        action='store_true',
        help='Compile the Bicep output to ARM template JSON (requires az bicep)'
    )
    
    args = parser.parse_args()
    
    # Setup logger
    logger = setup_logger()
    
    # Handle commands
    if args.command == 'convert':
        if args.source == 'file':
            # Validate input file exists
            if not os.path.exists(args.inputfile):
                logger.error(f"File not found - {args.inputfile}")
                return 1
            
            # Validate output folder is not a file
            if os.path.exists(args.outputfolder) and os.path.isfile(args.outputfolder):
                logger.error(f"Output folder is a file. Please specify a folder instead - {args.outputfolder}")
                return 1
            
            # Create converter
            converter = HealthModelConverter(logger)
            
            # Load V1 model
            logger.info(f"Reading input file '{args.inputfile}'...")
            v1_model = converter.load_v1_model(args.inputfile)
            if not v1_model:
                logger.error("Failed to deserialize v1 health model")
                return 1
            
            # Convert to Bicep
            logger.info(f"Converting health model '{v1_model.name}'...")
            bicep_content = converter.convert_v1_to_v2_bicep(v1_model)
            if not bicep_content:
                logger.error("Failed to convert health model to Bicep")
                return 1
            
            # Handle ARM template compilation if requested
            if args.armtemplate:
                # Check Bicep availability
                if not converter.check_bicep_availability():
                    logger.error("Cannot compile to ARM template. Please install Bicep by running: az bicep install")
                    return 1
                
                # Compile to ARM template
                arm_content = converter.compile_bicep_to_arm(bicep_content, v1_model.name)
                if not arm_content:
                    logger.error("Failed to compile Bicep to ARM template")
                    return 1
                
                # Write ARM template file
                if converter.write_output_file(arm_content, args.outputfolder, v1_model.name, ".json"):
                    logger.info(f"Health model '{v1_model.name}' converted to ARM template and written to output folder '{args.outputfolder}'")
                    
                    # Print deployment command
                    output_file = Path(args.outputfolder) / f"{v1_model.name}.json"
                    logger.info("")
                    logger.info("To deploy this health model to Azure, run:")
                    logger.info("")
                    logger.info(f"  az deployment group create \\")
                    logger.info(f"    --resource-group <YOUR_RESOURCE_GROUP> \\")
                    logger.info(f"    --template-file \"{output_file}\" \\")
                    logger.info(f"    --parameters resourceName=\"{v1_model.name}\" location=\"{SUPPORTED_V2_LOCATIONS[0]}\"")
                    logger.info("")
                    return 0
                else:
                    logger.error("Failed to write ARM template file")
                    return 1
            else:
                # Write Bicep file
                if converter.write_output_file(bicep_content, args.outputfolder, v1_model.name, ".bicep"):
                    logger.info(f"Health model '{v1_model.name}' converted to Bicep and written to output folder '{args.outputfolder}'")
                    
                    # Print deployment command
                    output_file = Path(args.outputfolder) / f"{v1_model.name}.bicep"
                    logger.info("")
                    logger.info("To deploy this health model to Azure, run:")
                    logger.info("")
                    logger.info(f"  az deployment group create \\")
                    logger.info(f"    --resource-group <YOUR_RESOURCE_GROUP> \\")
                    logger.info(f"    --template-file \"{output_file}\" \\")
                    logger.info(f"    --parameters resourceName=\"{v1_model.name}\" location=\"{SUPPORTED_V2_LOCATIONS[0]}\"")
                    logger.info("")
                    return 0
                else:
                    logger.error("Failed to write Bicep file")
                    return 1
        
        elif args.source == 'azure':
            # Check if Azure SDK is available
            if not AZURE_SDK_AVAILABLE:
                logger.error("Azure SDK is not installed. Please install with:")
                logger.error("  pip install azure-identity requests")
                return 1
            
            # Validate resource ID format
            if not validate_resource_id(args.resource_id):
                logger.error(f"Invalid resource ID format: {args.resource_id}")
                return 1
            
            # Validate output folder is not a file
            if os.path.exists(args.outputfolder) and os.path.isfile(args.outputfolder):
                logger.error(f"Output folder is a file. Please specify a folder instead - {args.outputfolder}")
                return 1
            
            # Create converter
            converter = HealthModelConverter(logger)
            
            # Fetch from Azure
            v1_model = converter.fetch_from_azure(args.resource_id)
            if not v1_model:
                logger.error("Failed to fetch or deserialize v1 health model from Azure")
                return 1
            
            # Convert to Bicep
            logger.info(f"Converting health model '{v1_model.name}'...")
            bicep_content = converter.convert_v1_to_v2_bicep(v1_model)
            if not bicep_content:
                logger.error("Failed to convert health model to Bicep")
                return 1
            
            # Handle ARM template compilation if requested
            if args.armtemplate:
                # Check Bicep availability
                if not converter.check_bicep_availability():
                    logger.error("Cannot compile to ARM template. Please install Bicep by running: az bicep install")
                    return 1
                
                # Compile to ARM template
                arm_content = converter.compile_bicep_to_arm(bicep_content, v1_model.name)
                if not arm_content:
                    logger.error("Failed to compile Bicep to ARM template")
                    return 1
                
                # Write ARM template file
                if converter.write_output_file(arm_content, args.outputfolder, v1_model.name, ".json"):
                    logger.info(f"Health model '{v1_model.name}' converted to ARM template and written to output folder '{args.outputfolder}'")
                    
                    # Print deployment command
                    output_file = Path(args.outputfolder) / f"{v1_model.name}.json"
                    logger.info("")
                    logger.info("To deploy this health model to Azure, run:")
                    logger.info("")
                    logger.info(f"  az deployment group create \\")
                    logger.info(f"    --resource-group <YOUR_RESOURCE_GROUP> \\")
                    logger.info(f"    --template-file \"{output_file}\" \\")
                    logger.info(f"    --parameters resourceName=\"{v1_model.name}\" location=\"{SUPPORTED_V2_LOCATIONS[0]}\"")
                    logger.info("")
                    return 0
                else:
                    logger.error("Failed to write ARM template file")
                    return 1
            else:
                # Write Bicep file
                if converter.write_output_file(bicep_content, args.outputfolder, v1_model.name, ".bicep"):
                    logger.info(f"Health model '{v1_model.name}' converted to Bicep and written to output folder '{args.outputfolder}'")
                    
                    # Print deployment command
                    output_file = Path(args.outputfolder) / f"{v1_model.name}.bicep"
                    logger.info("")
                    logger.info("To deploy this health model to Azure, run:")
                    logger.info("")
                    logger.info(f"  az deployment group create \\")
                    logger.info(f"    --resource-group <YOUR_RESOURCE_GROUP> \\")
                    logger.info(f"    --template-file \"{output_file}\" \\")
                    logger.info(f"    --parameters resourceName=\"{v1_model.name}\" location=\"{SUPPORTED_V2_LOCATIONS[0]}\"")
                    logger.info("")
                    return 0
                else:
                    logger.error("Failed to write Bicep file")
                    return 1
    
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())