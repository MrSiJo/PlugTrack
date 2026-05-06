# Changelog

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
