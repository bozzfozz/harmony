const SPOTIFY_PLAYLIST_ID_REGEX = /^[a-zA-Z0-9]+$/u;
const SPOTIFY_PLAYLIST_URL_REGEX = /^https?:\/\/open\.spotify\.com\/playlist\/([a-zA-Z0-9]+)(?:[/?].*)?$/iu;
const SPOTIFY_PLAYLIST_URI_REGEX = /^spotify:playlist:([a-zA-Z0-9]+)$/iu;

const normalizeInput = (value: string): string => value.trim();

export const extractPlaylistId = (value: string): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const input = normalizeInput(value);
  if (input.length === 0) {
    return null;
  }

  const urlMatch = input.match(SPOTIFY_PLAYLIST_URL_REGEX);
  if (urlMatch) {
    const [, playlistId] = urlMatch;
    return playlistId ?? null;
  }

  const uriMatch = input.match(SPOTIFY_PLAYLIST_URI_REGEX);
  if (uriMatch) {
    const [, playlistId] = uriMatch;
    return playlistId ?? null;
  }

  return null;
};

export const isSpotifyPlaylistLink = (value: string): boolean => {
  const playlistId = extractPlaylistId(value);
  return playlistId !== null && SPOTIFY_PLAYLIST_ID_REGEX.test(playlistId);
};

export const normalizeSpotifyPlaylistLink = (value: string): string | null => {
  const playlistId = extractPlaylistId(value);
  if (!playlistId) {
    return null;
  }
  return `https://open.spotify.com/playlist/${playlistId}`;
};
