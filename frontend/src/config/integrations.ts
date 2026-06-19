/**
 * INTEGRATIONS frontend config.
 *
 * Each entry describes one integration card on the Admin page:
 *  - key        unique identifier
 *  - label      display name
 *  - masterKey  the bool setting key that gates the integration
 *  - settingKeys ordered list of member setting keys shown inside the card
 *  - hint       optional advisory note shown below the card header
 *  - actions    action panels to render inside the card
 */

export interface IntegrationDef {
  key: string
  label: string
  /** The bool setting key that acts as the master on/off toggle. */
  masterKey: string
  /** Ordered list of member setting keys rendered inside the card. */
  settingKeys: string[]
  /** Advisory note shown below the card header (e.g. dependency warnings). */
  hint?: string
  /** Named action panels to render inside the card body. */
  actions?: ('testTelegram' | 'testOpenai' | 'clearPycupraTokens' | 'syncControls')[]
}

export const INTEGRATIONS: IntegrationDef[] = [
  {
    key: 'cupra',
    label: 'Cupra Connect',
    masterKey: 'pycupra_enabled',
    settingKeys: [
      'cupra_username',
      'cupra_password',
      'cupra_spin',
      'vehicle_provider',
      'sync_enabled',
      'sync_interval_minutes_idle',
      'sync_interval_minutes_plugged',
      'sync_interval_minutes_charging',
      'sync_daily_request_budget',
      'sync_quota_soft_fraction',
      'unconfirmed_soc_delta_threshold',
      'unconfirmed_regen_ceiling',
      'unconfirmed_stationary_tolerance_km',
    ],
    actions: ['clearPycupraTokens', 'syncControls'],
  },
  {
    key: 'telegram',
    label: 'Telegram',
    masterKey: 'telegram_bot_enabled',
    settingKeys: [
      'telegram_bot_token',
      'telegram_allowed_user_ids',
      'telegram_default_car_id',
    ],
    hint: 'Requires AI enabled for screenshot extraction.',
    actions: ['testTelegram'],
  },
  {
    key: 'ai',
    label: 'AI',
    masterKey: 'ai_enabled',
    settingKeys: [
      'ai_provider',
      'openai_api_key',
      'openai_model',
      'openai_input_price_per_1k_pence',
      'openai_output_price_per_1k_pence',
    ],
    actions: ['testOpenai'],
  },
  {
    key: 'geocoding',
    label: 'Geocoding',
    masterKey: 'geocoding_enabled',
    settingKeys: [
      'geocoding_provider',
      'geocoding_api_key',
      'location_cluster_radius_m',
    ],
  },
]
