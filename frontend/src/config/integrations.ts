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
  actions?: ('testTelegram' | 'testOpenai')[]
}

export const INTEGRATIONS: IntegrationDef[] = [
  {
    key: 'telegram',
    label: 'Telegram',
    masterKey: 'telegram_bot_enabled',
    settingKeys: [
      'telegram_bot_token',
      'telegram_allowed_user_ids',
      'digest_weekly_enabled',
      'digest_monthly_enabled',
      'digest_send_hour',
    ],
    hint: 'Screenshot extraction needs an OpenAI key set in the AI integration. Weekly and monthly digests are sent at the configured hour (Europe/London time).',
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
  {
    key: 'mqtt',
    label: 'MQTT / Home Assistant',
    masterKey: 'mqtt_enabled',
    settingKeys: [
      'mqtt_host',
      'mqtt_port',
      'mqtt_username',
      'mqtt_password',
      'mqtt_base_topic',
    ],
    hint: 'Publishes a retained charging summary to <base topic>/summary hourly and after every charge save.',
  },
]
