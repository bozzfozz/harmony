# Architecture Diagrams

## Request Flow
```mermaid
sequenceDiagram
    participant Client as Client
    participant Router as API Router
    participant Service as Application Service
    participant Gateway as ProviderGateway
    participant Provider as External Provider
    participant Core as Domain/Core

    Client->>Router: HTTP Request
    Router->>Service: Validated DTO + Idempotency-Key
    Service->>Core: Domain Operation (normalize/match)
    Core-->>Service: Domain Result
    Service->>Gateway: ProviderRequest DTO
    Gateway->>Provider: API Call (with timeout)
    Provider-->>Gateway: ProviderResponse
    Gateway-->>Service: Normalized DTO
    Service-->>Router: Response Payload
    Router-->>Client: JSON Response + Error Envelope on failure
```

## Orchestrator Flow
```mermaid
flowchart LR
    Scheduler[Scheduler\n(prioritised fetch)] -->|Lease job| Dispatcher[Dispatcher]
    Dispatcher --> Pools{Worker Pools}
    Pools -->|Dispatch| Handler[Job Handler]
    Handler -->|Process| Gateway
    Gateway[ProviderGateway/Services]
    Handler -->|Heartbeat| LeaseStore[(Visibility Store)]
    Handler -->|Ack success| Scheduler
    Handler -->|Fail w/ retry budget| RetryQueue[[Retry Queue]]
    RetryQueue --> Scheduler
    Handler -->|Exhausted budget| DLQ[(Dead Letter Queue)]
    DLQ --> Observability[Structured Logs\n`event=worker_job`]
    LeaseStore -->|Timeout| Scheduler
```
