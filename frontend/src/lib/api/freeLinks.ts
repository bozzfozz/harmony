import { apiUrl, ApiError, request } from '../../api/client';

export interface FreePlaylistLinkAccepted {
  playlist_id: string;
  url: string;
}

export type FreePlaylistSkipReason = 'duplicate' | 'invalid' | 'non_playlist' | string;

export interface FreePlaylistLinkSkipped {
  url: string;
  reason: FreePlaylistSkipReason;
}

export interface PostFreePlaylistLinksResponse {
  accepted: FreePlaylistLinkAccepted[];
  skipped: FreePlaylistLinkSkipped[];
}

export type PostFreePlaylistLinksPayload =
  | {
      url: string;
    }
  | {
      urls: string[];
    };

const FRIENDLY_MESSAGES: Record<number, string> = {
  429: 'Zu viele Versuche. Bitte warte einen Moment, bevor du es erneut probierst.',
};

const DEFAULT_SERVER_ERROR_MESSAGE = 'Der Dienst antwortet aktuell nicht. Bitte versuche es später erneut.';

export const postFreePlaylistLinks = async (
  payload: PostFreePlaylistLinksPayload
): Promise<PostFreePlaylistLinksResponse> => {
  try {
    return await request<PostFreePlaylistLinksResponse>({
      url: apiUrl('/spotify/free/links'),
      method: 'POST',
      data: payload,
      responseType: 'json'
    });
  } catch (error) {
    if (error instanceof ApiError) {
      const status = error.status ?? 0;
      if (status === 429 || status >= 500) {
        const message = FRIENDLY_MESSAGES[status] ?? DEFAULT_SERVER_ERROR_MESSAGE;
        throw new ApiError({
          code: error.code,
          message,
          status: error.status,
          details: error.details,
          requestId: error.requestId,
          url: error.url,
          method: error.method,
          cause: error.cause,
          body: error.body
        });
      }
    }
    throw error;
  }
};
