import { useCallback, useMemo } from 'react';

import { getSystemStatus } from '../api/services/system';
import { getIntegrations, type IntegrationsData } from '../api/services/soulseek';
import type { ConnectionStatus, SystemStatusResponse, WorkerHealth } from '../api/types';
import { useQuery } from '../lib/query';

type IntegrationService = 'soulseek' | 'matching';

type ServiceHealthMap = Record<IntegrationService, ServiceHealthState>;

const SERVICE_CONFIG: Record<IntegrationService, { connectionKeys: string[]; providerKeys: string[] }> = {
  soulseek: { connectionKeys: ['soulseek', 'slskd'], providerKeys: ['soulseek', 'slskd'] },
  matching: { connectionKeys: ['matching'], providerKeys: ['matching'] }
};

const normalizeStatus = (status?: string | null) => status?.toLowerCase() ?? 'unknown';

const isProblemStatus = (status?: string | null) => {
  const normalized = normalizeStatus(status);
  if (normalized === 'unknown') {
    return false;
  }
  return normalized !== 'ok' && normalized !== 'connected' && normalized !== 'running';
};

const hasMisconfiguration = (details?: Record<string, unknown> | null): boolean => {
  if (!details) {
    return false;
  }

  const values = Object.entries(details);
  if (values.length === 0) {
    return false;
  }

  return values.some(([key, value]) => {
    const normalizedKey = key.toLowerCase();
    if (normalizedKey.includes('missing') || normalizedKey.includes('unconfigured')) {
      if (Array.isArray(value)) {
        return value.length > 0;
      }
      if (typeof value === 'number') {
        return value > 0;
      }
      return Boolean(value);
    }

    if (normalizedKey.includes('error') || normalizedKey.includes('failure')) {
      return Boolean(value);
    }

    return false;
  });
};

const findMatchingEntry = <T,>(source: Record<string, T> | undefined, keys: string[]): [string, T] | undefined => {
  if (!source) {
    return undefined;
  }
  const lowerKeys = keys.map((key) => key.toLowerCase());
  return Object.entries(source).find(([name]) =>
    lowerKeys.some((key) => name.toLowerCase().includes(key))
  );
};

const findProvider = (integrations: IntegrationsData | undefined, keys: string[]) => {
  if (!integrations) {
    return undefined;
  }
  const lowerKeys = keys.map((key) => key.toLowerCase());
  return integrations.providers.find((provider) =>
    lowerKeys.some((key) => provider.name.toLowerCase().includes(key))
  );
};

export interface ServiceHealthState {
  online: boolean;
  degraded: boolean;
  misconfigured: boolean;
  status: string;
  connectionStatus?: ConnectionStatus;
  providerStatus?: string;
  workerStatus?: string;
  details?: Record<string, unknown> | null;
}

export interface UseIntegrationHealthResult {
  services: ServiceHealthMap;
  isLoading: boolean;
  errors: {
    system?: unknown;
    integrations?: unknown;
  };
  refresh: () => Promise<void>;
}

const emptyState: ServiceHealthState = {
  online: false,
  degraded: false,
  misconfigured: false,
  status: 'unknown'
};

const deriveOnlineFlag = (
  connectionStatus?: ConnectionStatus,
  providerStatus?: string,
  worker?: WorkerHealth
): boolean => {
  const connection = normalizeStatus(connectionStatus);
  const provider = normalizeStatus(providerStatus);
  const workerStatus = normalizeStatus(worker?.status);

  const connectionHealthy = connection === 'ok' || connection === 'connected';
  const providerHealthy = provider === 'ok' || provider === 'ready';
  const workerHealthy = worker?.status ? workerStatus === 'running' : true;

  return connectionHealthy && providerHealthy && workerHealthy;
};

const deriveServiceState = (
  service: IntegrationService,
  status: SystemStatusResponse | undefined,
  integrations: IntegrationsData | undefined
): ServiceHealthState => {
  const config = SERVICE_CONFIG[service];
  const connectionEntry = findMatchingEntry(status?.connections, config.connectionKeys);
  const workerEntry = service === 'matching' ? findMatchingEntry(status?.workers, config.connectionKeys) : undefined;
  const provider = findProvider(integrations, config.providerKeys);

  const connectionStatus = connectionEntry?.[1];
  const worker = workerEntry?.[1] as WorkerHealth | undefined;
  const providerStatus = provider?.status;

  const online = deriveOnlineFlag(connectionStatus, providerStatus, worker);
  const misconfigured = hasMisconfiguration(provider?.details);

  const degraded =
    misconfigured ||
    isProblemStatus(connectionStatus) ||
    isProblemStatus(providerStatus) ||
    isProblemStatus(worker?.status);

  const representativeStatus = normalizeStatus(
    providerStatus ?? (typeof connectionStatus === 'string' ? connectionStatus : undefined) ?? worker?.status ?? 'unknown'
  );

  return {
    online,
    degraded,
    misconfigured,
    status: representativeStatus,
    connectionStatus,
    providerStatus,
    workerStatus: worker?.status,
    details: provider?.details ?? undefined
  };
};

const useIntegrationHealth = (): UseIntegrationHealthResult => {
  const systemStatusQuery = useQuery<SystemStatusResponse>({
    queryKey: ['system', 'status'],
    queryFn: getSystemStatus,
    refetchInterval: 60000
  });

  const integrationsQuery = useQuery<IntegrationsData>({
    queryKey: ['integrations', 'overview'],
    queryFn: getIntegrations,
    refetchInterval: 60000
  });

  const services = useMemo<ServiceHealthMap>(() => {
    const systemStatus = systemStatusQuery.data;
    const integrations = integrationsQuery.data;

    const baseState: ServiceHealthMap = {
      soulseek: deriveServiceState('soulseek', systemStatus, integrations),
      matching: deriveServiceState('matching', systemStatus, integrations)
    };

    const hasSystemPayload = Boolean(systemStatus);
    const hasIntegrationsPayload = Boolean(integrations);
    const hasSystemError = systemStatusQuery.isError;
    const hasIntegrationsError = integrationsQuery.isError;
    const missingSystemPayload = !hasSystemPayload && !systemStatusQuery.isLoading;
    const missingIntegrationsPayload = !hasIntegrationsPayload && !integrationsQuery.isLoading;

    if (hasSystemError || hasIntegrationsError || missingSystemPayload || missingIntegrationsPayload) {
      return {
        soulseek: {
          ...baseState.soulseek,
          online: false,
          degraded: true,
          status: baseState.soulseek.status ?? 'unknown'
        },
        matching: {
          ...baseState.matching,
          online: false,
          degraded: true,
          status: baseState.matching.status ?? 'unknown'
        }
      };
    }

    return baseState;
  }, [
    integrationsQuery.data,
    integrationsQuery.isError,
    integrationsQuery.isLoading,
    systemStatusQuery.data,
    systemStatusQuery.isError,
    systemStatusQuery.isLoading
  ]);

  const refresh = useCallback(async () => {
    await Promise.all([systemStatusQuery.refetch(), integrationsQuery.refetch()]);
  }, [integrationsQuery, systemStatusQuery]);

  return {
    services: {
      soulseek: services.soulseek ?? emptyState,
      matching: services.matching ?? emptyState
    },
    isLoading: systemStatusQuery.isLoading || integrationsQuery.isLoading,
    errors: {
      system: systemStatusQuery.error,
      integrations: integrationsQuery.error
    },
    refresh
  };
};

export { useIntegrationHealth };
