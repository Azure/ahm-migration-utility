namespace Microsoft.CloudHealth.PreviewMigration.Models.V1;

public record HealthModel(
    string id,
    string name,
    string type,
    string location,
    Dictionary<string, string>? tags,
    SystemData? systemData,
    Identity? identity,
    Properties properties
);

public record SystemData(
    string createdBy,
    string createdByType,
    string createdAt,
    string lastModifiedBy,
    string lastModifiedByType,
    string lastModifiedAt
);

public record Identity(
    string principalId,
    string tenantId,
    string type,
    Dictionary<string, UserAssignedIdentity>? userAssignedIdentities
);

public record UserAssignedIdentity(
    string principalId,
    string clientId
);

public record Properties(
    string versionNumber,
    string activeState,
    string refreshInterval,
    string provisioningState,
    Node[]? nodes
);

public record Node(
    string nodeType,
    string nodeId,
    string name,
    string[]? childNodeIds,
    Visual? visual,
    string impact,
    string azureResourceId,
    string credentialId,
    Query[]? queries,
    string nodeKind,
    string logAnalyticsResourceId,
    string logAnalyticsWorkspaceId,
    string azureMonitorWorkspaceResourceId,
    string queryEndpoint,
    double? healthTargetPercentage = null
);

public record Visual(
    int x,
    int y
);

public record Query(
    string queryType,
    string metricName,
    string metricNamespace,
    string aggregationType,
    string queryId,
    string degradedThreshold,
    string degradedOperator,
    string unhealthyThreshold,
    string unhealthyOperator,
    string timeGrain,
    string dataUnit,
    string enabledState,
    string name,
    string queryText,
    string? valueColumnName,
    string dataType,
    string? dimension,
    string? dimensionFilter
);