/**
 * Mobius Identity token client (OPT-6).
 *
 * Mint and cache JWTs via POST /auth/login for machine callers (Terminal cron).
 * Use a dedicated service account — never a founder wallet or human operator JWT.
 */

/**
 * @param {string} token
 * @returns {number | null}
 */
function jwtExpUnix(token) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const decoded = JSON.parse(
      typeof Buffer !== 'undefined'
        ? Buffer.from(padded, 'base64url').toString('utf8')
        : atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
    );
    return typeof decoded.exp === 'number' ? decoded.exp : null;
  } catch {
    return null;
  }
}

class IdentityTokenClient {
  /**
   * @param {object} options
   * @param {string} options.baseUrl - Mobius Identity base URL (no /auth suffix)
   * @param {string} options.email - Service account email
   * @param {string} options.password - Service account password
   * @param {number} [options.refreshMarginSeconds=86400] - Refresh this many seconds before JWT exp
   * @param {typeof fetch} [options.fetchImpl] - fetch implementation (for tests)
   */
  constructor({ baseUrl, email, password, refreshMarginSeconds = 86400, fetchImpl }) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.email = email;
    this.password = password;
    this.refreshMarginSeconds = refreshMarginSeconds;
    this.fetchImpl = fetchImpl || (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null);
    if (!this.fetchImpl) {
      throw new Error('fetch is required (pass fetchImpl in Node < 18)');
    }
    /** @type {string | null} */
    this._token = null;
    /** @type {number | null} */
    this._expiresAt = null;
  }

  /**
   * Build from process.env (Node) or explicit env object.
   * @param {Record<string, string | undefined>} [env]
   */
  static fromEnv(env = typeof process !== 'undefined' ? process.env : {}) {
    const base =
      (env.IDENTITY_API_BASE || env.IDENTITY_SERVICE_URL || '').trim();
    const email = (env.IDENTITY_SERVICE_EMAIL || '').trim();
    const password = (env.IDENTITY_SERVICE_PASSWORD || '').trim();
    const missing = [];
    if (!base) missing.push('IDENTITY_API_BASE');
    if (!email) missing.push('IDENTITY_SERVICE_EMAIL');
    if (!password) missing.push('IDENTITY_SERVICE_PASSWORD');
    if (missing.length) {
      throw new Error(`Missing env for IdentityTokenClient: ${missing.join(', ')}`);
    }
    const margin = parseInt(env.IDENTITY_TOKEN_REFRESH_MARGIN_SECONDS || '86400', 10);
    return new IdentityTokenClient({
      baseUrl: base,
      email,
      password,
      refreshMarginSeconds: Number.isFinite(margin) ? margin : 86400,
    });
  }

  _needsRefresh() {
    if (!this._token) return true;
    if (this._expiresAt == null) return true;
    return Date.now() / 1000 >= this._expiresAt - this.refreshMarginSeconds;
  }

  /**
   * POST /auth/login and cache access_token.
   * @returns {Promise<{ access_token: string, token_type: string, user: object }>}
   */
  async login() {
    const response = await this.fetchImpl(`${this.baseUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: this.email, password: this.password }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Identity login failed (${response.status}): ${text}`);
    }
    const data = await response.json();
    this._token = data.access_token;
    this._expiresAt = jwtExpUnix(data.access_token);
    return data;
  }

  /**
   * @param {{ forceRefresh?: boolean }} [options]
   * @returns {Promise<string>}
   */
  async getToken({ forceRefresh = false } = {}) {
    if (forceRefresh || this._needsRefresh()) {
      const data = await this.login();
      return data.access_token;
    }
    return /** @type {string} */ (this._token);
  }

  /**
   * @param {{ forceRefresh?: boolean }} [options]
   * @returns {Promise<Record<string, string>>}
   */
  async getAuthorizationHeader(options = {}) {
    const token = await this.getToken(options);
    return { Authorization: `Bearer ${token}` };
  }

  /**
   * @param {string} [token]
   */
  async introspect(token) {
    const bearer = token || (await this.getToken());
    const response = await this.fetchImpl(`${this.baseUrl}/auth/introspect`, {
      headers: { Authorization: `Bearer ${bearer}` },
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Identity introspect failed (${response.status}): ${text}`);
    }
    return response.json();
  }

  /**
   * POST /ledger/attest; retries once with forced refresh on 401.
   */
  async attest(ledgerUrl, { eventType, civicId, payload, labSource = 'terminal', forceRefresh = false }) {
    const headers = {
      ...(await this.getAuthorizationHeader({ forceRefresh })),
      'Content-Type': 'application/json',
    };
    const body = {
      event_type: eventType,
      civic_id: civicId,
      lab_source: labSource,
      payload,
    };
    const url = `${ledgerUrl.replace(/\/$/, '')}/ledger/attest`;
    let response = await this.fetchImpl(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    if (response.status === 401 && !forceRefresh) {
      return this.attest(ledgerUrl, {
        eventType,
        civicId,
        payload,
        labSource,
        forceRefresh: true,
      });
    }
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Ledger attest failed (${response.status}): ${text}`);
    }
    return response.json();
  }
}

export { IdentityTokenClient, jwtExpUnix };
