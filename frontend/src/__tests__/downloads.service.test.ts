import { startDownload, retryDownload } from '../api/services/downloads';
import type { StartDownloadPayload } from '../api/types';
import { apiUrl, request } from '../api/client';

jest.mock('../api/client', () => {
  const actual = jest.requireActual('../api/client');
  return {
    ...actual,
    apiUrl: jest.fn((path: string) => path),
    request: jest.fn()
  };
});

describe('downloads service normalization', () => {
  const mockedRequest = request as jest.MockedFunction<typeof request>;
  const mockedApiUrl = apiUrl as jest.MockedFunction<typeof apiUrl>;

  beforeEach(() => {
    mockedRequest.mockReset();
    mockedApiUrl.mockReset();
    mockedApiUrl.mockImplementation((path: string) => path);
  });

  it('normalizes responses with download_id envelopes into DownloadEntry', async () => {
    mockedRequest.mockResolvedValueOnce({ ok: true, data: { download_id: 321 } });

    const payload: StartDownloadPayload = {
      username: ' User ',
      files: [
        {
          filename: 'song.mp3'
        }
      ]
    };

    const entry = await startDownload(payload);

    expect(mockedRequest).toHaveBeenCalledWith({
      method: 'POST',
      url: '/download',
      data: {
        username: 'User',
        files: [
          {
            filename: 'song.mp3',
            name: 'song.mp3'
          }
        ]
      }
    });

    expect(entry).toMatchObject({
      id: 321,
      status: 'queued',
      progress: 0,
      priority: 0,
      filename: ''
    });
  });

  it('extracts entries from downloads arrays when retrying', async () => {
    mockedRequest.mockResolvedValueOnce({
      downloads: [
        {
          id: 77,
          filename: 'retry.mp3',
          status: 'running',
          progress: 25,
          priority: 2
        }
      ]
    });

    const entry = await retryDownload(12);

    expect(mockedRequest).toHaveBeenCalledWith({ method: 'POST', url: '/download/12/retry' });
    expect(entry).toEqual(
      expect.objectContaining({
        id: 77,
        filename: 'retry.mp3',
        status: 'running',
        progress: 25,
        priority: 2
      })
    );
  });

  it('prefers returned download_id values over retry arguments', async () => {
    mockedRequest.mockResolvedValueOnce({ download_id: 'new-id' });

    const entry = await retryDownload(55);

    expect(entry.id).toBe('new-id');
    expect(entry.status).toBe('queued');
    expect(entry.progress).toBe(0);
  });
});
