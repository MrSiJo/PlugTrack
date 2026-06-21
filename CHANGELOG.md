# Changelog

## [3.5.0](https://github.com/MrSiJo/PlugTrack/compare/v3.4.2...v3.5.0) (2026-06-21)


### Features

* blended two-phase charge planner + Wh/mi efficiency figure ([#41](https://github.com/MrSiJo/PlugTrack/issues/41)) ([425adf5](https://github.com/MrSiJo/PlugTrack/commit/425adf5fba55304b2049ac0d367579678d88227c))

## [3.4.2](https://github.com/MrSiJo/PlugTrack/compare/v3.4.1...v3.4.2) (2026-06-20)


### Bug Fixes

* planner SoC defaults & input UX; docs: README refresh ([#33](https://github.com/MrSiJo/PlugTrack/issues/33)) ([4c36e91](https://github.com/MrSiJo/PlugTrack/commit/4c36e91d03939c7d58b5fb7393ac2a65b44f18a1))

## [3.4.1](https://github.com/MrSiJo/PlugTrack/compare/v3.4.0...v3.4.1) (2026-06-20)


### Bug Fixes

* planner home-actual & AC ceiling, car-form persistence, insights polish ([#31](https://github.com/MrSiJo/PlugTrack/issues/31)) ([e2f7a06](https://github.com/MrSiJo/PlugTrack/commit/e2f7a0655f6ffc0aac09833fe66677359ed77e2d))

## [3.4.0](https://github.com/MrSiJo/PlugTrack/compare/v3.3.0...v3.4.0) (2026-06-20)


### Features

* long-term ownership trends — seasonal efficiency & battery health ([#29](https://github.com/MrSiJo/PlugTrack/issues/29)) ([aaa4e12](https://github.com/MrSiJo/PlugTrack/commit/aaa4e12ed31e38f1444ba3976c7c0732afe79f24))

## [3.3.0](https://github.com/MrSiJo/PlugTrack/compare/v3.2.0...v3.3.0) (2026-06-20)


### Features

* proactive summaries — scheduled Telegram digest ([#27](https://github.com/MrSiJo/PlugTrack/issues/27)) ([c78773f](https://github.com/MrSiJo/PlugTrack/commit/c78773f3175a4721ebc2d4258fd9014134bd6d87))

## [3.2.0](https://github.com/MrSiJo/PlugTrack/compare/v3.1.0...v3.2.0) (2026-06-20)


### Features

* smart charge planner — multi-scenario, data-driven ([#25](https://github.com/MrSiJo/PlugTrack/issues/25)) ([9860868](https://github.com/MrSiJo/PlugTrack/commit/9860868ed1c4091d8deb2eb7dfe2649bc81de2a4))

## [3.1.0](https://github.com/MrSiJo/PlugTrack/compare/v3.0.0...v3.1.0) (2026-06-20)


### Features

* multi-car support (names, archive, per-charge targeting, lifetime review) ([#23](https://github.com/MrSiJo/PlugTrack/issues/23)) ([7794b63](https://github.com/MrSiJo/PlugTrack/commit/7794b630f7240fa8ce1b6b7a310e4e4db0f8234a))

## [3.0.0](https://github.com/MrSiJo/PlugTrack/compare/v2.11.1...v3.0.0) (2026-06-20)


### ⚠ BREAKING CHANGES

* the Cupra Connect / pycupra sync integration is removed. Charge data is now ingested exclusively via the Telegram screenshot bot.

### Features

* remove pycupra/Cupra sync subsystem (standalone pivot) ([928a5d6](https://github.com/MrSiJo/PlugTrack/commit/928a5d6c35d675cd2f518e2c2fd52420e0fd31c7))

## [2.11.1](https://github.com/MrSiJo/PlugTrack/compare/v2.11.0...v2.11.1) (2026-06-20)


### Bug Fixes

* **security:** harden CSV export, VIN paths, rate-limit key, MCP limit ([2c6c831](https://github.com/MrSiJo/PlugTrack/commit/2c6c831263cf24afafeee867e40e5cc19e294399))

## [2.11.0](https://github.com/MrSiJo/PlugTrack/compare/v2.10.2...v2.11.0) (2026-06-20)


### Features

* **bot:** edit session mileage by chat/screenshot + current-date awareness for relative dates ([bf20e6c](https://github.com/MrSiJo/PlugTrack/commit/bf20e6c86deb7415141c9e4cc0eda77c77450cc1))
* **bot:** update an existing session from a screenshot (caption + conversational triggers) ([c1fa582](https://github.com/MrSiJo/PlugTrack/commit/c1fa5825f655378386a734b74999d7fbb19d796b))
* conversational session editing — screenshots, mileage, dates ([3473c64](https://github.com/MrSiJo/PlugTrack/commit/3473c648cb62bed0b8a867035e92dca6c9cb947a))


### Bug Fixes

* **bot:** harden screenshot-to-edit parsers + card/token state (review fixes) ([dca1825](https://github.com/MrSiJo/PlugTrack/commit/dca18255d1c5b0ffbd0474a0dbee21f382749a33))
* **bot:** treat falsy location_id as no filter in find_charges ([119154b](https://github.com/MrSiJo/PlugTrack/commit/119154b1c75f0c9fca36b42415650e3875d2f391))

## [2.10.2](https://github.com/MrSiJo/PlugTrack/compare/v2.10.1...v2.10.2) (2026-06-20)


### Bug Fixes

* **bot:** money totals in pounds, rates in pence ([cb21211](https://github.com/MrSiJo/PlugTrack/commit/cb212112f94b4f26ed4500c6d85de89430dc0332))
* **bot:** present money totals in pounds, rates in pence ([1d83dbe](https://github.com/MrSiJo/PlugTrack/commit/1d83dbefc9b58f34d0963da8e8e63d4aee00bce1))

## [2.10.1](https://github.com/MrSiJo/PlugTrack/compare/v2.10.0...v2.10.1) (2026-06-20)


### Bug Fixes

* **bot:** flat Responses API function-tool shape ([b383d70](https://github.com/MrSiJo/PlugTrack/commit/b383d7037cf3fc1b64a8b534f2825a83be16643c))
* **bot:** use flat Responses API function-tool shape ([a0d7af5](https://github.com/MrSiJo/PlugTrack/commit/a0d7af5d73defa6bba1b7735fda2f059869c32bf))

## [2.10.0](https://github.com/MrSiJo/PlugTrack/compare/v2.9.0...v2.10.0) (2026-06-19)


### Features

* **admin:** MCP token management (mint/list/revoke) ([b330b11](https://github.com/MrSiJo/PlugTrack/commit/b330b110244cd1b8467dd370de69dac22a6547b5))
* **bot:** agentic tool-calling loop replacing read-only usage chat ([fa5a243](https://github.com/MrSiJo/PlugTrack/commit/fa5a243ddd13359d34f55a2a6d5669fa519846c1))
* MCP server + agentic Telegram bot (spec 05) ([5440a0a](https://github.com/MrSiJo/PlugTrack/commit/5440a0a920f0b1a792096cd0f1639fd98eab36ec))
* **mcp:** per-user MCP token model + service (hashed, scoped, revocable) ([076f612](https://github.com/MrSiJo/PlugTrack/commit/076f612d13282823d42a36f3429eabc3f66504e8))
* **mcp:** streamable-HTTP MCP server at /mcp with bearer-token auth + scopes ([0cb4315](https://github.com/MrSiJo/PlugTrack/commit/0cb43151358b65eb44226ca578cd7d37506c0a94))
* **mcp:** user-scoped tool core with two-phase propose/commit ([3dcac01](https://github.com/MrSiJo/PlugTrack/commit/3dcac01ed2e051b6b4091d4d6ba1f2a4a9992516))


### Bug Fixes

* **bot:** wire ai_enabled through load_bot_config + reconcile so the agent loop is live ([a0de622](https://github.com/MrSiJo/PlugTrack/commit/a0de6226ca70428fe9c4c29ac4a44f128bd21eb2))
* **mcp:** geocode address at propose, purge change-store, test location filter ([fcd6c9c](https://github.com/MrSiJo/PlugTrack/commit/fcd6c9c0ec9583e4b37463e2b83bf1cd02ee4143))

## [2.9.0](https://github.com/MrSiJo/PlugTrack/compare/v2.8.0...v2.9.0) (2026-06-19)


### Features

* **admin:** backup + export UI in Maintenance panel ([f570ceb](https://github.com/MrSiJo/PlugTrack/commit/f570ceb1ea09c6bfae74e2890d5ad144b7ca9f24))
* backup & export (spec 06) ([2d9e7da](https://github.com/MrSiJo/PlugTrack/commit/2d9e7da46ac510c09dffbccdebd8c54f25882c7e))
* **backup:** scheduled rotating snapshots via APScheduler ([2419803](https://github.com/MrSiJo/PlugTrack/commit/24198039eb7631c7be1341943416949ff3347ab4))
* **backup:** VACUUM INTO snapshot service with keep-last-N pruning ([9c31965](https://github.com/MrSiJo/PlugTrack/commit/9c31965478e02059b27745ca78585e25a0377dce))
* **export:** user-scoped sessions CSV/JSON export service ([4004e68](https://github.com/MrSiJo/PlugTrack/commit/4004e68de348a6bb13b422ef18160032d2a7dec0))
* **maintenance:** backup + sessions export endpoints (auth-gated, traversal-safe) ([b80e0ba](https://github.com/MrSiJo/PlugTrack/commit/b80e0bacc733b4569669ad5b64d1349a6d3f623d))
* **settings:** add backup_enabled/interval/retention keys ([b211240](https://github.com/MrSiJo/PlugTrack/commit/b211240383cd322b7f8531577ff73de62a7d255f))


### Bug Fixes

* **backup:** clamp backup interval and guard scheduler wiring against boot crash ([65ca906](https://github.com/MrSiJo/PlugTrack/commit/65ca90607a0143014a49584815b96927d1f8f510))

## [2.8.0](https://github.com/MrSiJo/PlugTrack/compare/v2.7.1...v2.8.0) (2026-06-19)


### Features

* **admin:** add INTEGRATIONS frontend config ([c54bc8f](https://github.com/MrSiJo/PlugTrack/commit/c54bc8f0b00ae683ad96323f541139ba58b2072b))
* **admin:** AdminPage shell with Integrations + Preferences; route /admin ([e34cecb](https://github.com/MrSiJo/PlugTrack/commit/e34cecb0f3646cf5b24c0d0a7649059f1149e26a))
* **admin:** IntegrationCard with master-toggle gating + single Save ([86d10b4](https://github.com/MrSiJo/PlugTrack/commit/86d10b44704a02102f24e6abaf1d801856b3bb91))
* Administration page (spec 04) ([4fcf70d](https://github.com/MrSiJo/PlugTrack/commit/4fcf70d96807e4f49c5ae221d16ecdc6ba72f740))
* **admin:** MaintenancePanel (CSV import/backfill remain CLI; backup/export to follow) ([c1a7908](https://github.com/MrSiJo/PlugTrack/commit/c1a7908b39907671c35c3f4549efe93d82fae106))
* **admin:** master-detail layout with left section rail ([7acd585](https://github.com/MrSiJo/PlugTrack/commit/7acd5854ad8b1de3415207bab5be2302a2c75d96))
* **admin:** PreferencesPanel ([0b35ca9](https://github.com/MrSiJo/PlugTrack/commit/0b35ca96b8e9d9c43be6c22a7019d6a8e86f09e5))
* **admin:** relocate cars management + VIN reveal-on-edit into Admin ([33dcb2b](https://github.com/MrSiJo/PlugTrack/commit/33dcb2bdbff2297785d371ada4226c6dbea027b5))
* **admin:** relocate locations management (create/delete/merge) into Admin ([c88a9d2](https://github.com/MrSiJo/PlugTrack/commit/c88a9d24f8795c74ed35e3267ffccad6c9ef42d5))
* **cars:** mask VIN in payload, add owner-gated reveal endpoint ([2263103](https://github.com/MrSiJo/PlugTrack/commit/22631036b6040be0506a3730776e758d5d589aa3))
* **client:** add revealCarVin ([0040b80](https://github.com/MrSiJo/PlugTrack/commit/0040b803b4dadb7f5beca86883060d649d5e9dfe))
* **dashboard:** add Plan a charge entry point (Planner left main nav) ([52b04ae](https://github.com/MrSiJo/PlugTrack/commit/52b04ae3049c4372dd11d792a062741e6d2dc6f0))
* **nav:** replace Settings link with /admin gear icon ([6abe637](https://github.com/MrSiJo/PlugTrack/commit/6abe63711fb2bf46525d985a9213bb0a288e17a5))
* **settings:** add ai_enabled + ai_provider keys, regroup openai_* under ai ([d020754](https://github.com/MrSiJo/PlugTrack/commit/d0207544ba176041c016670a44127acc1983f53f))
* **settings:** seed ai_enabled=true when an OpenAI key already exists ([e8c781c](https://github.com/MrSiJo/PlugTrack/commit/e8c781c771f498bf71e6b827812a96c90242d98e))


### Bug Fixes

* **admin:** correct Telegram card AI-key hint ([ed4be36](https://github.com/MrSiJo/PlugTrack/commit/ed4be361e5d9ac11c317fe6fe564705f0e88e26f))
* **admin:** guard VIN reveal against cross-car race in edit ([e908e9d](https://github.com/MrSiJo/PlugTrack/commit/e908e9d01dab3aea2481aef232bc048f08b26985))
* **admin:** resync IntegrationCard master toggle when settings hydrate ([25824fe](https://github.com/MrSiJo/PlugTrack/commit/25824fe3e633afc79564f7d7223e22e60d078acf))
* **cars:** don't persist masked VIN when reveal fails (frontend guard + backend reject) ([be81b39](https://github.com/MrSiJo/PlugTrack/commit/be81b39ba038751580ad0e0f679461735a3181e7))
* **cars:** fully mask VINs of 5 or fewer characters ([bd9c5a1](https://github.com/MrSiJo/PlugTrack/commit/bd9c5a1bfb9ca9b6c87f99802d3e350c325bfa87))
* **dashboard:** show masked VIN on car card ([2260597](https://github.com/MrSiJo/PlugTrack/commit/2260597ba76e14b27edea0475cc0b99e023ed0ba))

## [2.7.1](https://github.com/MrSiJo/PlugTrack/compare/v2.7.0...v2.7.1) (2026-06-19)


### Bug Fixes

* **ui:** drive dark mode from the .dark class, not OS scheme ([c26123e](https://github.com/MrSiJo/PlugTrack/commit/c26123e5dc6b4ba81dde81723036845200f86150))

## [2.7.0](https://github.com/MrSiJo/PlugTrack/compare/v2.6.0...v2.7.0) (2026-06-19)


### Features

* **insights:** add numeric aggregator service ([83ffce5](https://github.com/MrSiJo/PlugTrack/commit/83ffce57b6974d6bb7f4cb45ab855b6a3f141fb2))
* **insights:** add per-car mileage allowance view ([7365240](https://github.com/MrSiJo/PlugTrack/commit/73652408954df3be486b058a800b3f7796675829))
* **insights:** assemble additional modules into the Insights page ([de5a665](https://github.com/MrSiJo/PlugTrack/commit/de5a665572bbdcaa49bed7a58dbb6a2bffa3d6c3))
* **insights:** client types + overview/mileage methods ([74187a5](https://github.com/MrSiJo/PlugTrack/commit/74187a57277656f1bb630d8e88486c3dd7aa87a9))
* **insights:** design pass — card-wrap modules, fix mileage unit casing ([c3a9a5d](https://github.com/MrSiJo/PlugTrack/commit/c3a9a5d608b6e6c0b193349c8b049d05aa2d8c4f))
* **insights:** mileage allowance / pace component ([430ba87](https://github.com/MrSiJo/PlugTrack/commit/430ba8793f1eed0b6720a963d95bd1fe8f49cc54))
* **insights:** over-time, split, network & efficiency chart components ([b9d7a04](https://github.com/MrSiJo/PlugTrack/commit/b9d7a04abcc61f9f9b3ea1c9fe046777497a6d2d))
* **insights:** overview + mileage endpoints ([d3a82f3](https://github.com/MrSiJo/PlugTrack/commit/d3a82f3e29add0ee16fe1f59fadd99680af524dd))


### Bug Fixes

* **insights:** UTC mileage date + honest over-allowance KPI ([209331b](https://github.com/MrSiJo/PlugTrack/commit/209331bdd3b78165b397bcf788b730bf95e3b4f3))

## [2.6.0](https://github.com/MrSiJo/PlugTrack/compare/v2.5.0...v2.6.0) (2026-06-19)


### Features

* **cost:** bake location rate into frozen override on delete ([1fc049d](https://github.com/MrSiJo/PlugTrack/commit/1fc049d07561f19959c904674d38687c3706adf1))
* **cost:** freeze session cost on edit — re-scale at stored tariff ([b90d363](https://github.com/MrSiJo/PlugTrack/commit/b90d363a563eb0eef03104b29d882747ea9951a5))
* **cost:** make first-label forward-only, keep network backfill ([4414d42](https://github.com/MrSiJo/PlugTrack/commit/4414d42f160caf82ba1831200f81354f343f07a5))
* **curves:** read AC curves + add screenshot curve-backfill CLI ([bcd2a36](https://github.com/MrSiJo/PlugTrack/commit/bcd2a36a469c3a9dd361ccf3cf63a78d7d93f26c))
* **insights:** add by-location breakdown endpoint ([76dd8a5](https://github.com/MrSiJo/PlugTrack/commit/76dd8a52a647bfa5f36a4341297fcfb64b79e422))
* **insights:** add Insights page with by-location breakdown ([006e0b2](https://github.com/MrSiJo/PlugTrack/commit/006e0b2f9cbeec7bb8209be06456abaec4837b8d))
* **insights:** add location detail page ([7bcc857](https://github.com/MrSiJo/PlugTrack/commit/7bcc8571aca55bb8bad2cca415f69cbf402ceb80))
* **insights:** wire /insights and /locations/:id routes + nav ([5c98347](https://github.com/MrSiJo/PlugTrack/commit/5c98347507ea0801c387e161077c9cb0376d0f0f))
* **locations:** assign location from session edit + forward-geocode address search ([b37bf65](https://github.com/MrSiJo/PlugTrack/commit/b37bf65f197e27a30ba6707f1f80580d9ad385d7))
* **sessions:** redesign detail page + extract DC charge curves ([6edc7a0](https://github.com/MrSiJo/PlugTrack/commit/6edc7a02944ca7e308b224ed657131aed1a9fafd))


### Bug Fixes

* **insights:** dark-mode-aware chart tooltip ([87b553e](https://github.com/MrSiJo/PlugTrack/commit/87b553e66a67678588690d2d7f885552166fbf09))
* **insights:** reconcile detail header with breakdown; review nits ([98c8d68](https://github.com/MrSiJo/PlugTrack/commit/98c8d687a2cff84f81f88e3fea1de5046f77a29d))

## [2.5.0](https://github.com/MrSiJo/PlugTrack/compare/v2.4.0...v2.5.0) (2026-06-18)


### Features

* **dashboard:** add cost-per-mile KPI (lifetime + rolling 30d) ([0be7903](https://github.com/MrSiJo/PlugTrack/commit/0be7903ffdb5c71c4ea713d7210e14d58c41ea65))
* **sessions:** actual charge time + MyCupra CSV backfill importer ([0b6c37f](https://github.com/MrSiJo/PlugTrack/commit/0b6c37fb4672ca346cc903b3645815b828c03fc8))


### Bug Fixes

* **ingest:** parse photo captions for mileage + home location ([3f8f0c9](https://github.com/MrSiJo/PlugTrack/commit/3f8f0c9bfb496a99dd15976bb6d0a4283b09ce9d))
* **ingest:** restore peak_kw to required; don't black-hole text on charge-parse error ([3643b14](https://github.com/MrSiJo/PlugTrack/commit/3643b14b291047400e10853fbcad838e13e705b6))
* **metrics:** derive average power from actual charge time, not plug-in window ([84443b2](https://github.com/MrSiJo/PlugTrack/commit/84443b212f43ab6184a6e7544233104ce80279ca))
* **sessions:** allow telegram + import in the source filter allow-list ([f967b33](https://github.com/MrSiJo/PlugTrack/commit/f967b3361c6b17d1da518c57dfcb80d51ab81109))
* **usage:** answer in plain text (the bot sends no parse_mode, so markdown showed literally) ([f65f594](https://github.com/MrSiJo/PlugTrack/commit/f65f594ed29d297b4ba9955dbcc4493108bc4bd5))

## [2.4.0](https://github.com/MrSiJo/PlugTrack/compare/v2.3.0...v2.4.0) (2026-06-17)


### Features

* **api:** expose battery_care + max_charge_current on sessions ([c785923](https://github.com/MrSiJo/PlugTrack/commit/c785923b2dd8a50c21b844f5731544bba18b60d7))
* **api:** telegram test/openai-models endpoints, lifespan wiring + usage columns ([d775a5e](https://github.com/MrSiJo/PlugTrack/commit/d775a5e9e7f3cee55fef56e574348d7cb5b63550))
* **cars:** migrate existing cupra_connect cars to standalone provider=manual ([b613e00](https://github.com/MrSiJo/PlugTrack/commit/b613e00430ae0921f35ce03e588179ef648bc1de))
* **dashboard:** expose live battery-care + current cap + est-end ([2c4e934](https://github.com/MrSiJo/PlugTrack/commit/2c4e934b922047ea1914b7ab4a246b7699651a52))
* **geocoding:** add forward (address -&gt; coords) to providers ([b08b1ef](https://github.com/MrSiJo/PlugTrack/commit/b08b1efb68aba2d07864b6ffcac747c7944734db))
* **ingest:** backfill Locations for existing import sessions ([32c54a2](https://github.com/MrSiJo/PlugTrack/commit/32c54a2b222cac0b20bdcc114ad6857c3aa04251))
* **ingest:** bot config, health report, manager, /test command + enriched card ([c1241e9](https://github.com/MrSiJo/PlugTrack/commit/c1241e9412106a6d6424477a6d49b6ada430fc14))
* **ingest:** capture odometer in extraction schema + prompts ([8855e1b](https://github.com/MrSiJo/PlugTrack/commit/8855e1bc0bb56f40f017602581017a14486b367e))
* **ingest:** carry location_short_name through MergedSession ([97bd6d2](https://github.com/MrSiJo/PlugTrack/commit/97bd6d2e8d4dcbbfe5660e3c8afbfcae0305ffc9))
* **ingest:** carry odometer through MergedSession correlation ([7d58094](https://github.com/MrSiJo/PlugTrack/commit/7d580940b813107d0b405b0d9af6d9fa9f47120e))
* **ingest:** commit merged screenshot session with override_total + dedupe ([777a95a](https://github.com/MrSiJo/PlugTrack/commit/777a95a3fe6b47a62b8d0cf72563b8ee11d7cbb2))
* **ingest:** create/link geocoded Location on Save (commit-only) ([3875bba](https://github.com/MrSiJo/PlugTrack/commit/3875bbaae7f1e99630a8a00f9a7769c00d5d0870))
* **ingest:** edit the confirm card in place as screenshots merge ([ca5e76a](https://github.com/MrSiJo/PlugTrack/commit/ca5e76abaf4e85ce1dc1c6b33599f868a29903a1))
* **ingest:** extract location_short_name (&lt;Network&gt; &lt;Place&gt; label) ([7f7a22c](https://github.com/MrSiJo/PlugTrack/commit/7f7a22c521eb37665fb0a1119a4d0b898dc8adcf))
* **ingest:** geocode + cluster resolver with &lt;Network&gt; &lt;Place&gt; naming ([af28365](https://github.com/MrSiJo/PlugTrack/commit/af28365d75fb59f30d206ad12e85c0d993b4813d))
* **ingest:** granny/EVSE vision source + free-text charge-note extraction ([27e4663](https://github.com/MrSiJo/PlugTrack/commit/27e46632f77c7f47c2b77d4e8f349d6914e44017))
* **ingest:** home-aware commit — delivered vs banked, ac/dc, location, rate cost ([a7ec277](https://github.com/MrSiJo/PlugTrack/commit/a7ec27758478a5f63e8f7282c4ff3b2101037eef))
* **ingest:** long-poll telegram runner wired into lifespan (gated) ([98d69da](https://github.com/MrSiJo/PlugTrack/commit/98d69da4232385d696880d88235f32037d611bb1))
* **ingest:** minimal async Telegram Bot API client ([f82646b](https://github.com/MrSiJo/PlugTrack/commit/f82646b06d564bcba76c0e491c702eb431f78b82))
* **ingest:** openai model admin + Responses API extraction (reasoning off, usage) ([335f3d7](https://github.com/MrSiJo/PlugTrack/commit/335f3d769e2930df021811995dd3809ea44e49ea))
* **ingest:** OpenAI vision extraction service for charge screenshots ([6f183c0](https://github.com/MrSiJo/PlugTrack/commit/6f183c0478a30d15809aace27077ba87cac78ee1))
* **ingest:** persist odometer_at_session_km with unit resolution ([7305151](https://github.com/MrSiJo/PlugTrack/commit/7305151650bb37bbd52e485b0902f1b858d030a5))
* **ingest:** place undated granny/AC readings under one-charge-per-Save ([0baf40d](https://github.com/MrSiJo/PlugTrack/commit/0baf40d4500d1444662b0579f18ba19bac7f2bf4))
* **ingest:** show odometer + regression warning on confirm card ([5d48225](https://github.com/MrSiJo/PlugTrack/commit/5d4822541803d8398ba1e65c26348ad656c670da))
* **ingest:** show projected cost on the confirm card; drop "?" placeholders ([430dcfa](https://github.com/MrSiJo/PlugTrack/commit/430dcfab3b584473299b8b330b88e196b0431693))
* **ingest:** tag Telegram-ingested sessions as "telegram" (was "import") ([5d00cc9](https://github.com/MrSiJo/PlugTrack/commit/5d00cc95294918245501e3ba64c5482d9c701ca8))
* **ingest:** telegram caption + free-text routing, richer card + Save cost ([8c8aecb](https://github.com/MrSiJo/PlugTrack/commit/8c8aecb681fd0f06d92234de8fa417ae4746df8a))
* **ingest:** telegram photo/callback handlers (stage-&gt;correlate-&gt;commit) ([00bd76f](https://github.com/MrSiJo/PlugTrack/commit/00bd76faa69bf8a2bc26bd82f586c594b730c264))
* **ingest:** time-window correlation + source-priority merge (golden-tested) ([96aeb20](https://github.com/MrSiJo/PlugTrack/commit/96aeb2070e22507baa04f4e2b59df6eae402a319))
* **metrics:** energy-based petrol comparison fallback when no odometer ([b0ee8c7](https://github.com/MrSiJo/PlugTrack/commit/b0ee8c7e44229c961cc8da73bbeefc6b0cb39021))
* **metrics:** per-charge energy-based savings + break-even rate signal ([1f32fb2](https://github.com/MrSiJo/PlugTrack/commit/1f32fb26cb65f132bfd798281b1d43ef7e7c65dd))
* **models:** add ScreenshotImport staging table ([ccdcb61](https://github.com/MrSiJo/PlugTrack/commit/ccdcb610b0e51e6f315b096e3129d07e7989f75a))
* **models:** charge-context columns w/ additive migration ([e9c4c87](https://github.com/MrSiJo/PlugTrack/commit/e9c4c87bb8d10c47ad8ea15cdbf2950dbee96f48))
* **planner:** home charge-time + cost estimator with multi-night windows ([5751560](https://github.com/MrSiJo/PlugTrack/commit/57515604440f78e35dc1a2f088b27e9856ccb0a3))
* **pycupra:** adapter reads charging_mode/battery_care/max_current/est_end ([c5a9c1d](https://github.com/MrSiJo/PlugTrack/commit/c5a9c1d2e925b15dc457aec8b8a56a7659278efe))
* **pycupra:** add charge-context fields to VehicleState ([33594d5](https://github.com/MrSiJo/PlugTrack/commit/33594d584dc0f00f7e39087713bab2e261e57ffd))
* **sessions:** complete "unconfirmed" SoC-delta charges (rename from phantom) ([ba1aa5d](https://github.com/MrSiJo/PlugTrack/commit/ba1aa5dbc4a9c9657b53207ee9db442427dab6b7))
* **sessions:** derive kwh_calculated from SoC delta on create + update ([837e76f](https://github.com/MrSiJo/PlugTrack/commit/837e76f72d32ca039df051433a0a7de85c9a3667))
* **sessions:** edit charge start/end time + interrupted flag ([7e6064c](https://github.com/MrSiJo/PlugTrack/commit/7e6064c647dffcde433daf73ae2f539ed0b41eea))
* **sessions:** populate charging_mode + context from telemetry ([06587b2](https://github.com/MrSiJo/PlugTrack/commit/06587b21c0fb1b4c629315491c649dc8af11f32f))
* **sessions:** show mode/type hint in sessions list rows ([406ec13](https://github.com/MrSiJo/PlugTrack/commit/406ec130f713194d3cf6e0224dfd64cf991c1e7f))
* **sessions:** sortable table with per-row savings + custom date filter ([2dfdb54](https://github.com/MrSiJo/PlugTrack/commit/2dfdb54379549fb1c1788fc3e8e433483dec9c62))
* **sessions:** surface range, duration, power, efficiency per session ([5f1fea7](https://github.com/MrSiJo/PlugTrack/commit/5f1fea793f12d90a553b0d3a4c4ccaf065128a72))
* **settings:** add telegram/openai config + pycupra_enabled gate keys ([91b0af7](https://github.com/MrSiJo/PlugTrack/commit/91b0af78cb68b8efdfe4f28639d7cbbac6fd727a))
* **settings:** public_base_url + openai price-per-1k catalogue keys ([13d1e3a](https://github.com/MrSiJo/PlugTrack/commit/13d1e3ad00aa1fc99b0061d78d0cb3010676ef20))
* **sync:** daily request quota guard; remove wake feature ([67680a1](https://github.com/MrSiJo/PlugTrack/commit/67680a15a5033480ddce062a2888d7a0a581b799))
* **sync:** gate pycupra stack behind pycupra_enabled (default off) ([1311cd9](https://github.com/MrSiJo/PlugTrack/commit/1311cd9ddb48ea0d954b42e2c65139578f384432))
* **sync:** persist session + live charge-context ([989530f](https://github.com/MrSiJo/PlugTrack/commit/989530f72d9ece4878e97eb96ae789a58c5c80b3))
* **sync:** phantom-charge detection, orphan watchdog, visit tracking ([b138497](https://github.com/MrSiJo/PlugTrack/commit/b138497ad684d69570accdda853c82bb27c816cc))
* **ui:** battery-care pill + estimated-end on HeroCarCard ([6f26b10](https://github.com/MrSiJo/PlugTrack/commit/6f26b10298a8b9de924d4c121d85bf631635a8d4))
* **ui:** client types for charge context ([e10589a](https://github.com/MrSiJo/PlugTrack/commit/e10589a01aa0fa3965bf476a6986794a50b25b6f))
* **ui:** manual charge-session create + manual location add ([3f27e76](https://github.com/MrSiJo/PlugTrack/commit/3f27e7658a6c4b4a4b5d1026e9b036c0501a90d4))
* **ui:** SessionDetail charge-context section + edit inputs ([206e563](https://github.com/MrSiJo/PlugTrack/commit/206e563715f3c64dac1a11db2be0ac223b568c88))
* **ui:** telegram test-connection panel + dynamic openai model dropdown ([527be54](https://github.com/MrSiJo/PlugTrack/commit/527be5415197405d79439af757133bc1d66d7b5b))
* **ui:** telegram/openai settings groups + hide sync when pycupra disabled ([d5a7674](https://github.com/MrSiJo/PlugTrack/commit/d5a7674b1fc05684b06fc69a5b45f827e73addcd))
* **usage:** add miles-driven + petrol comparison per window to chat snapshot ([2ec6ac0](https://github.com/MrSiJo/PlugTrack/commit/2ec6ac09e7c4f2e5ab66986b901c7e4974ff99f2))
* **usage:** grounded usage-question answerer over snapshot ([91c82e9](https://github.com/MrSiJo/PlugTrack/commit/91c82e92434ac5f2e406d70be1de31ef350a8cbf))
* **usage:** home/public + by-network split in usage snapshot ([1c86b1b](https://github.com/MrSiJo/PlugTrack/commit/1c86b1b485c338dab0ba4341c85b834407196773))
* **usage:** mileage + annual pace in usage snapshot ([9e4dc0e](https://github.com/MrSiJo/PlugTrack/commit/9e4dc0ee052fb9691e09d219ea8e02cfba9d3306))
* **usage:** route non-charge Telegram text to the usage answerer ([95f80db](https://github.com/MrSiJo/PlugTrack/commit/95f80dbf8d489732fa35ed2ed1f61eb57dd2e4ca))
* **usage:** windowed charging-stats snapshot with pre-rendered values ([2c0117e](https://github.com/MrSiJo/PlugTrack/commit/2c0117e04e4211017451f37a70a80ac208ab7826))


### Bug Fixes

* **dashboard:** rank top locations by charge count, not visit_count ([60d11b6](https://github.com/MrSiJo/PlugTrack/commit/60d11b6296f7a3ab07e78ca868d8c13f833ce9cd))
* **deps:** bump pycupra to v0.2.33 ([086b565](https://github.com/MrSiJo/PlugTrack/commit/086b565989d3a594ba20d06cdf3a6d2bc74fcb5d))
* **geocoding:** harden OpenCage/Mapbox forward stubs; tidy commit logger placement ([10801ca](https://github.com/MrSiJo/PlugTrack/commit/10801cadcfbdeb553148bfb1de1a5f11538cf893))
* **ingest:** fall back to UK postcode when full address fails to geocode ([f3a2eb7](https://github.com/MrSiJo/PlugTrack/commit/f3a2eb777f9a749e34759b9f41b660c57a0d0880))
* **ingest:** make Telegram health check accurate during setup ([25ef8bc](https://github.com/MrSiJo/PlugTrack/commit/25ef8bcd941ae1078a3cfe6284c36e8aec38dfc1))
* **ingest:** normalize odometer unit aliases (miles/kilometres) to km ([2fdd829](https://github.com/MrSiJo/PlugTrack/commit/2fdd8296979f96488a65aa70ae663846e349ee1b))
* **ingest:** re-stageable discards + duplicate-screenshot guard ([ff9d8d5](https://github.com/MrSiJo/PlugTrack/commit/ff9d8d5334a41ac70a9e62fb17b6d84b94b3611e))
* **metrics:** stop chain absorbing later odometer-less manual charges ([b0631c5](https://github.com/MrSiJo/PlugTrack/commit/b0631c56875b9bcb8446cf3c5001f4ef98208fca))
* **probe:** avoid invoking instance property getters during introspection ([fa7392a](https://github.com/MrSiJo/PlugTrack/commit/fa7392a5244c02689e79866ecb12a86407585cce))
* **security:** harden cookies, headers, CSRF, and per-user job isolation ([02f1c5b](https://github.com/MrSiJo/PlugTrack/commit/02f1c5ba63cb1b39e12d5171cc4378893528cd41))
* **sync:** bump pycupra to v0.2.32 to fix Cupra garage 403 ([d45b25d](https://github.com/MrSiJo/PlugTrack/commit/d45b25d52a8ae15c500987ad0ab4bac6a13ffa73))
* **sync:** classify provider auth failures and surface them in the UI ([29c4f45](https://github.com/MrSiJo/PlugTrack/commit/29c4f4505f1d6c81022a2fadf995b98bd112e1cf))
* **sync:** surface live charge-context on the dashboard ([e1044ac](https://github.com/MrSiJo/PlugTrack/commit/e1044ac91c736ce485aa44d2865ceb822a04eb24))
* **ui:** listen on IPv6 so the container healthcheck passes ([19c63b1](https://github.com/MrSiJo/PlugTrack/commit/19c63b177a8ccb55cc676f5b512271b95c065a87))
* **usage:** hedge home/public split in prompt; tighten usage tests ([b322270](https://github.com/MrSiJo/PlugTrack/commit/b322270cec39f5f95823cd00f3395b6dd9d5407c))

## [2.3.0](https://github.com/MrSiJo/PlugTrack/compare/v2.2.0...v2.3.0) (2026-05-06)


### Features

* **cars:** add per-car annual mileage tracker ([59d8c6f](https://github.com/MrSiJo/PlugTrack/commit/59d8c6f173ee21c40e9be70b4e795d96000aa45b))

## [2.2.0](https://github.com/MrSiJo/PlugTrack/compare/v2.1.0...v2.2.0) (2026-05-05)


### Features

* **api:** add date_from/date_to/source/location_id filters to GET /api/sessions ([711c173](https://github.com/MrSiJo/PlugTrack/commit/711c173633c2bae4b7419c6bd656d08e90ba227a))
* **api:** add GET /api/dashboard/spend-trend ([2ab890b](https://github.com/MrSiJo/PlugTrack/commit/2ab890b65b85e8161e021b4a9383bc5a84569dd8))
* **api:** add getSpendTrend client wrapper ([2bc252c](https://github.com/MrSiJo/PlugTrack/commit/2bc252c639a69a1015e1784fff45a53af337ff76))
* **cars:** redesign Cars page with primitives, per-car pycupra image, drop redundant Vehicle ID line ([c9a69ef](https://github.com/MrSiJo/PlugTrack/commit/c9a69efb51945c654c9088feb98b098e9d7b0c78))
* **dashboard:** add HeroCarCard with gradient battery and live charging pill ([c035669](https://github.com/MrSiJo/PlugTrack/commit/c03566922f7dec672fea4830e4cca2455d295f02))
* **dashboard:** add SpendChart with gradient bars (Recharts) ([8d811e2](https://github.com/MrSiJo/PlugTrack/commit/8d811e283323c4e7332c4ac65f2aa1cffc8da322))
* **dashboard:** rebuild dashboard with HeroCarCard, SpendChart, StatTile strip ([7dfcf6a](https://github.com/MrSiJo/PlugTrack/commit/7dfcf6aa4b2693d2b0ef25f97c50a7f8cebfae92))
* **frontend:** add cn() class-name helper ([6add775](https://github.com/MrSiJo/PlugTrack/commit/6add7750c32798dc80b65a886673a9469eb23b37))
* **frontend:** add Electric-palette design tokens and Inter font ([925d432](https://github.com/MrSiJo/PlugTrack/commit/925d4327dd54902fc913786a1e98cf9e05730f89))
* **frontend:** add groupSessionsByMonth helper ([4caed28](https://github.com/MrSiJo/PlugTrack/commit/4caed280ef98408771477db8548c8b73f1344c64))
* **frontend:** import Leaflet stylesheet globally ([b8489f0](https://github.com/MrSiJo/PlugTrack/commit/b8489f0c7ae51b5a3264e95ac36e2d14f18732a4))
* **locations:** add Leaflet map with cost-band markers and OSM/CartoDB tiles ([a8ea861](https://github.com/MrSiJo/PlugTrack/commit/a8ea8613d7fa4eafeeba06260c7960efc3437b1e))
* **pages:** apply primitives to Cars/Login/Setup with gradient logo ([ff32802](https://github.com/MrSiJo/PlugTrack/commit/ff3280227ab89316fc990a07aaba6bc9e2913400))
* **session-detail:** add duration tile, location mini-map, drop cost-breakdown panel, rework petrol comparison as KPI tiles ([dc282e5](https://github.com/MrSiJo/PlugTrack/commit/dc282e597323d4f00c4268deedaeb58772922c54))
* **session:** redesign detail with hero summary, gradient figures, cost-basis tooltip ([163836a](https://github.com/MrSiJo/PlugTrack/commit/163836af1b4701a7fcc3d9e9fb48ccdcd0d26fa9))
* **sessions:** redesign list with month grouping, filters, gradient cost ([514aaa6](https://github.com/MrSiJo/PlugTrack/commit/514aaa6cb191b53bd0850b81280d488623a9b215))
* **shell:** build command palette with navigation + theme toggle (Ctrl+K) ([fb9c831](https://github.com/MrSiJo/PlugTrack/commit/fb9c8316d545e8b46916f7dd28a4ecea914a3681))
* **shell:** bump page max-width to max-w-7xl across all routes ([c9c531c](https://github.com/MrSiJo/PlugTrack/commit/c9c531c5404371d0e04b74c1583d9a044070a2aa))
* **shell:** refine NavBar with gradient logo, electric active state, search trigger ([397ed89](https://github.com/MrSiJo/PlugTrack/commit/397ed893c63926ddabbc9743f8edb715a0602acc))
* **ui:** add Card primitive with default/hero/muted variants ([4d7bbcb](https://github.com/MrSiJo/PlugTrack/commit/4d7bbcbd6a14b54d94d88196a0d72efb4cef3f65))
* **ui:** add EmptyState and PageHeader primitives ([a33659f](https://github.com/MrSiJo/PlugTrack/commit/a33659fd04963b650799fca0bbb5d38d35606c7f))
* **ui:** add GradientNumber primitive ([cd62280](https://github.com/MrSiJo/PlugTrack/commit/cd6228016e003c586dd6a3e0f2535504cf8f4e47))
* **ui:** add Pill primitive with 6 tone variants ([91285e5](https://github.com/MrSiJo/PlugTrack/commit/91285e57a5581ecd00d34e2e5c63adcf70f11c37))
* **ui:** add ProgressBar primitive with gradient + pulse ([0c95e99](https://github.com/MrSiJo/PlugTrack/commit/0c95e99986c20729da499ea5508bb620696d4694))
* **ui:** add StatTile primitive ([5c53b9a](https://github.com/MrSiJo/PlugTrack/commit/5c53b9ae50e390bf6168a7f01504f69e6eae5b34))
* **ui:** install shadcn primitives (button, dialog, tabs, tooltip, popover, dropdown-menu, command, input, label, switch) ([774af58](https://github.com/MrSiJo/PlugTrack/commit/774af58332d0d902570583edce7ee3d21f261c81))

## [2.1.0](https://github.com/MrSiJo/PlugTrack/compare/plugtrack-v2.0.0...plugtrack-v2.1.0) (2026-05-05)


### Features

* **api:** add date_from/date_to/source/location_id filters to GET /api/sessions ([711c173](https://github.com/MrSiJo/PlugTrack/commit/711c173633c2bae4b7419c6bd656d08e90ba227a))
* **api:** add GET /api/dashboard/spend-trend ([2ab890b](https://github.com/MrSiJo/PlugTrack/commit/2ab890b65b85e8161e021b4a9383bc5a84569dd8))
* **api:** add getSpendTrend client wrapper ([2bc252c](https://github.com/MrSiJo/PlugTrack/commit/2bc252c639a69a1015e1784fff45a53af337ff76))
* **cars:** redesign Cars page with primitives, per-car pycupra image, drop redundant Vehicle ID line ([c9a69ef](https://github.com/MrSiJo/PlugTrack/commit/c9a69efb51945c654c9088feb98b098e9d7b0c78))
* **dashboard:** add HeroCarCard with gradient battery and live charging pill ([c035669](https://github.com/MrSiJo/PlugTrack/commit/c03566922f7dec672fea4830e4cca2455d295f02))
* **dashboard:** add SpendChart with gradient bars (Recharts) ([8d811e2](https://github.com/MrSiJo/PlugTrack/commit/8d811e283323c4e7332c4ac65f2aa1cffc8da322))
* **dashboard:** rebuild dashboard with HeroCarCard, SpendChart, StatTile strip ([7dfcf6a](https://github.com/MrSiJo/PlugTrack/commit/7dfcf6aa4b2693d2b0ef25f97c50a7f8cebfae92))
* **frontend:** add cn() class-name helper ([6add775](https://github.com/MrSiJo/PlugTrack/commit/6add7750c32798dc80b65a886673a9469eb23b37))
* **frontend:** add Electric-palette design tokens and Inter font ([925d432](https://github.com/MrSiJo/PlugTrack/commit/925d4327dd54902fc913786a1e98cf9e05730f89))
* **frontend:** add groupSessionsByMonth helper ([4caed28](https://github.com/MrSiJo/PlugTrack/commit/4caed280ef98408771477db8548c8b73f1344c64))
* **frontend:** import Leaflet stylesheet globally ([b8489f0](https://github.com/MrSiJo/PlugTrack/commit/b8489f0c7ae51b5a3264e95ac36e2d14f18732a4))
* **locations:** add Leaflet map with cost-band markers and OSM/CartoDB tiles ([a8ea861](https://github.com/MrSiJo/PlugTrack/commit/a8ea8613d7fa4eafeeba06260c7960efc3437b1e))
* **pages:** apply primitives to Cars/Login/Setup with gradient logo ([ff32802](https://github.com/MrSiJo/PlugTrack/commit/ff3280227ab89316fc990a07aaba6bc9e2913400))
* **session-detail:** add duration tile, location mini-map, drop cost-breakdown panel, rework petrol comparison as KPI tiles ([dc282e5](https://github.com/MrSiJo/PlugTrack/commit/dc282e597323d4f00c4268deedaeb58772922c54))
* **session:** redesign detail with hero summary, gradient figures, cost-basis tooltip ([163836a](https://github.com/MrSiJo/PlugTrack/commit/163836af1b4701a7fcc3d9e9fb48ccdcd0d26fa9))
* **sessions:** redesign list with month grouping, filters, gradient cost ([514aaa6](https://github.com/MrSiJo/PlugTrack/commit/514aaa6cb191b53bd0850b81280d488623a9b215))
* **shell:** build command palette with navigation + theme toggle (Ctrl+K) ([fb9c831](https://github.com/MrSiJo/PlugTrack/commit/fb9c8316d545e8b46916f7dd28a4ecea914a3681))
* **shell:** bump page max-width to max-w-7xl across all routes ([c9c531c](https://github.com/MrSiJo/PlugTrack/commit/c9c531c5404371d0e04b74c1583d9a044070a2aa))
* **shell:** refine NavBar with gradient logo, electric active state, search trigger ([397ed89](https://github.com/MrSiJo/PlugTrack/commit/397ed893c63926ddabbc9743f8edb715a0602acc))
* **ui:** add Card primitive with default/hero/muted variants ([4d7bbcb](https://github.com/MrSiJo/PlugTrack/commit/4d7bbcbd6a14b54d94d88196a0d72efb4cef3f65))
* **ui:** add EmptyState and PageHeader primitives ([a33659f](https://github.com/MrSiJo/PlugTrack/commit/a33659fd04963b650799fca0bbb5d38d35606c7f))
* **ui:** add GradientNumber primitive ([cd62280](https://github.com/MrSiJo/PlugTrack/commit/cd6228016e003c586dd6a3e0f2535504cf8f4e47))
* **ui:** add Pill primitive with 6 tone variants ([91285e5](https://github.com/MrSiJo/PlugTrack/commit/91285e57a5581ecd00d34e2e5c63adcf70f11c37))
* **ui:** add ProgressBar primitive with gradient + pulse ([0c95e99](https://github.com/MrSiJo/PlugTrack/commit/0c95e99986c20729da499ea5508bb620696d4694))
* **ui:** add StatTile primitive ([5c53b9a](https://github.com/MrSiJo/PlugTrack/commit/5c53b9ae50e390bf6168a7f01504f69e6eae5b34))
* **ui:** install shadcn primitives (button, dialog, tabs, tooltip, popover, dropdown-menu, command, input, label, switch) ([774af58](https://github.com/MrSiJo/PlugTrack/commit/774af58332d0d902570583edce7ee3d21f261c81))
