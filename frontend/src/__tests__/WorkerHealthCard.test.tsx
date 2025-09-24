import { render, screen } from '@testing-library/react';
import WorkerHealthCard from '../components/WorkerHealthCard';

const fixedNow = new Date('2025-01-01T12:00:00Z').getTime();

describe('WorkerHealthCard', () => {
  beforeEach(() => {
    jest.spyOn(Date, 'now').mockReturnValue(fixedNow);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders running worker information', () => {
    render(
      <WorkerHealthCard
        workerName="sync_worker"
        status="running"
        queueSize={3}
        lastSeen="2025-01-01T11:59:30Z"
      />
    );

    expect(screen.getByText('Sync Worker')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('vor 30s')).toBeInTheDocument();
  });

  it('renders stopped worker without last seen data', () => {
    render(
      <WorkerHealthCard workerName="autosync" status="stopped" queueSize="n/a" lastSeen={null} />
    );

    expect(screen.getByText('Autosync')).toBeInTheDocument();
    expect(screen.getByText('Stopped')).toBeInTheDocument();
    expect(screen.getByText('n/a')).toBeInTheDocument();
    expect(screen.getByText('Keine Daten')).toBeInTheDocument();
  });

  it('renders stale worker with structured queue information', () => {
    render(
      <WorkerHealthCard
        workerName="matching"
        status="stale"
        queueSize={{ scheduled: 2, running: 1 }}
        lastSeen="2024-12-31T12:00:00Z"
      />
    );

    expect(screen.getByText('Matching')).toBeInTheDocument();
    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText('scheduled: 2 • running: 1')).toBeInTheDocument();
    expect(screen.getByText('vor 1d')).toBeInTheDocument();
  });
});
