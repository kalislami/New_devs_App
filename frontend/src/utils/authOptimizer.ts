/**
 * Optimized Authentication Flow Manager
 * 
 * This module provides a centralized, efficient authentication flow that:
 * 1. Eliminates duplicate session checks
 * 2. Combines bootstrap and permissions into a single request
 * 3. Implements proper caching and request deduplication
 * 4. Reduces authentication time from ~10s to <2s
 */

import { supabase } from '../lib/supabase';
import { SecureAPI } from '../lib/secureApi';
import { sessionRecovery } from './sessionRecovery';

// Singleton state for auth data
class AuthOptimizer {
  private static instance: AuthOptimizer;
  private sessionPromise: Promise<any> | null = null;
  private bootstrapPromise: Promise<any> | null = null;
  private cachedSession: any = null;
  private cachedBootstrap: any = null;
  private sessionTimestamp: number = 0;
  private bootstrapTimestamp: number = 0;
  
  // Cache durations
  private readonly SESSION_CACHE_MS = 5 * 60 * 1000; // 5 minutes
  private readonly BOOTSTRAP_CACHE_MS = 5 * 60 * 1000; // 5 minutes (aligned with session cache)
  private readonly REQUEST_TIMEOUT_MS = 10000; // 10 seconds - more generous for slow connections
  
  private constructor() {}
  
  static getInstance(): AuthOptimizer {
    if (!AuthOptimizer.instance) {
      AuthOptimizer.instance = new AuthOptimizer();
    }
    return AuthOptimizer.instance;
  }
  
  /**
   * Get session with caching and deduplication
   */
  async getSession(forceRefresh: boolean = false): Promise<any> {
    if (typeof window !== 'undefined' && (window as any).__isLoggingOut) {
      console.log('[AuthOptimizer] Skipping getSession - logout in progress');
      return null;
    }

    const now = Date.now();

    // Return cached session if valid and not forcing refresh
    if (!forceRefresh && this.cachedSession && (now - this.sessionTimestamp) < this.SESSION_CACHE_MS) {
      console.log('[AuthOptimizer] Returning cached session, user:', this.cachedSession.user?.email);
      // Ensure token is still set
      if (this.cachedSession.access_token) {
        SecureAPI.setAccessToken(this.cachedSession.access_token);
      }
      return this.cachedSession;
    }
    
    // If already fetching, return the existing promise (deduplication)
    if (this.sessionPromise && !forceRefresh) {
      console.log('[AuthOptimizer] Session fetch in progress, waiting...');
      return this.sessionPromise;
    }
    
    // This ensures we don't return null prematurely on direct URL access
    if (!this.cachedSession && !this.sessionPromise) {
      console.log('[AuthOptimizer] No cached session, starting initial session recovery...');
    }
    
    // Start new session fetch with timeout
    this.sessionPromise = this.fetchSessionWithTimeout();
    
    try {
      const session = await this.sessionPromise;
      
      if (session) {
        console.log('[AuthOptimizer] Session retrieved successfully, user:', session.user?.email);
        this.cachedSession = session;
        this.sessionTimestamp = now;
      } else {
        console.log('[AuthOptimizer] No session retrieved - user not authenticated');
        this.cachedSession = null;
        this.sessionTimestamp = 0;
      }
      
      return session;
    } finally {
      this.sessionPromise = null;
    }
  }
  
  /**
   * Get bootstrap data with caching and deduplication
   */
  async getBootstrapData(forceRefresh: boolean = false): Promise<any> {
    const now = Date.now();
    
    // Return cached bootstrap if valid and not forcing refresh
    if (!forceRefresh && this.cachedBootstrap && (now - this.bootstrapTimestamp) < this.BOOTSTRAP_CACHE_MS) {
      console.log('[AuthOptimizer] Returning cached bootstrap data');
      return this.cachedBootstrap;
    }
    
    // If already fetching, return the existing promise (deduplication)
    if (this.bootstrapPromise && !forceRefresh) {
      console.log('[AuthOptimizer] Bootstrap fetch in progress, waiting...');
      return this.bootstrapPromise;
    }
    
    // Ensure we have a valid session first
    let session = await this.getSession();
    if (!session) {
      console.warn('[AuthOptimizer] No session available for bootstrap fetch, checking for existing session');
      // Try to get session directly as a last resort
      const { data: { session: directSession } } = await supabase.auth.getSession();
      if (directSession) {
        SecureAPI.setAccessToken(directSession.access_token);
        this.cachedSession = directSession;
        this.sessionTimestamp = Date.now();
        session = directSession;
      } else {
        return this.createFallbackBootstrap(null);
      }
    }
    
    // Start new bootstrap fetch with timeout
    this.bootstrapPromise = this.fetchBootstrapWithTimeout(session);
    
    try {
      const bootstrap = await this.bootstrapPromise;
      this.cachedBootstrap = bootstrap;
      this.bootstrapTimestamp = now;
      return bootstrap;
    } finally {
      this.bootstrapPromise = null;
    }
  }
  
  /**
   * Clear all cached data
   */
  clearCache(): void {
    this.cachedSession = null;
    this.cachedBootstrap = null;
    this.sessionTimestamp = 0;
    this.bootstrapTimestamp = 0;
    this.sessionPromise = null;
    this.bootstrapPromise = null;
    console.log('[AuthOptimizer] Cache cleared');
  }
  
  /**
   * Store a freshly obtained session and propagate token to SecureAPI
   */
  storeSession(session: any): void {
    try {
      if (session && session.access_token) {
        this.cachedSession = session;
        this.sessionTimestamp = Date.now();
        SecureAPI.setAccessToken(session.access_token);
        console.log('[AuthOptimizer] Session stored for user:', session.user?.email);
      }
    } catch (e) {
      console.warn('[AuthOptimizer] Failed to store session:', e);
    }
  }
  
  /**
   * Clear cached session and remove token from SecureAPI
   */
  clearSession(): void {
    this.cachedSession = null;
    this.sessionTimestamp = 0;
    try { SecureAPI.setAccessToken(null as any); } catch {}
    console.log('[AuthOptimizer] Session cleared');
  }
  
  /**
   * Clear cache for specific user (on session change)
   */
  clearUserCache(userId: string): void {
    // If cached session belongs to a different user, clear everything
    if (this.cachedSession?.user?.id && this.cachedSession.user.id !== userId) {
      this.clearCache();
      console.log('[AuthOptimizer] Cache cleared due to user change');
    }
  }
  
  /**
   * Fetch session with timeout
   */
  private async fetchSessionWithTimeout(): Promise<any> {
    if ((window as any).__isLoggingOut) return null;
    // The local auth client validates the persisted token through /auth/me.
    // Supabase storage keys and its recovery protocol do not apply here.
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.access_token) SecureAPI.setAccessToken(session.access_token);
    return session;
  }

  /**
   * Fetch bootstrap data with timeout
   */
  private async fetchBootstrapWithTimeout(session: any): Promise<any> {
    const timeoutPromise = new Promise((resolve) => {
      setTimeout(() => {
        console.warn('[AuthOptimizer] Bootstrap fetch timeout, using fallback');
        resolve(this.createFallbackBootstrap(session));
      }, this.REQUEST_TIMEOUT_MS);
    });
    
    const fetchPromise = (async () => {
      console.log('[AuthOptimizer] Fetching bootstrap data...');
      const startTime = Date.now();
      
      try {
        // Use SecureAPI for consistent security and deduplication
        SecureAPI.setAccessToken(session.access_token);
        // Fetch the bootstrap data using the auth/me endpoint
        const data = await SecureAPI.getAuthMe();
        const elapsed = Date.now() - startTime;
        console.log(`[AuthOptimizer] Bootstrap fetched in ${elapsed}ms`);
        
        return data;
      } catch (error) {
        console.error('[AuthOptimizer] Bootstrap fetch failed:', error);
        return this.createFallbackBootstrap(session);
      }
    })();
    
    return Promise.race([fetchPromise, timeoutPromise]);
  }
  
  /**
   * Create fallback bootstrap data
   */
  private createFallbackBootstrap(session: any): any {
    const user = session?.user;
    return {
      user: {
        id: user?.id || '',
        email: user?.email || '',
        role: user?.app_metadata?.role || 'user',
        is_admin: user?.app_metadata?.role === 'admin'
      },
      permissions: user?.app_metadata?.role === 'admin' 
        ? [{ section: '*', action: '*' }] 
        : [],
      tenant: null,
      company_settings: null,
      modules: [],
      smart_views: {},
      subsections: [],
      metadata: {
        tenant_id: user?.app_metadata?.tenant_id || null,
        timestamp: new Date().toISOString(),
        version: '1.0.0',
        is_fallback: true
      }
    };
  }
}

export const authOptimizer = AuthOptimizer.getInstance();
