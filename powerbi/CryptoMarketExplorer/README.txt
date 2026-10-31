Crypto Market Explorer - Power BI project (PBIP)

A .pbix is produced by Power BI Desktop on Windows; this folder is the
text-based Power BI Project that Desktop opens directly.

Windows steps
-------------
1. Install the latest 64-bit Power BI Desktop.
2. Copy this whole folder (keep the .pbip, .Report and .SemanticModel
   together) to Windows.
3. Start the project database and make it reachable:
     docker compose up -d db backend
   Default connection: localhost:5432 / crypto_market_explorer
   User: crypto   Password: crypto_dev_password
   If Desktop runs in a VM or on another PC, use
   Home > Transform data > Edit parameters > PostgresServer and set the
   database host's LAN IP instead of localhost.
4. Open CryptoMarketExplorer.pbip.
   The first open has no cached data, so visuals are blank.
5. Home > Refresh, enter the database credentials, and wait for the import.
   If Power BI asks for Npgsql, install the 64-bit Npgsql provider and
   restart Desktop.
6. File > Save as > Power BI file (*.pbix). The refreshed .pbix embeds the
   imported data and is self-contained.

Pages: Market Overview, Compare Pairs, Data Quality.
The pair slicer starts on Bitcoin, the timeframe on 15m, and the date
slicer covers 2026-09-28 to 2026-10-27 (UTC).

See powerbi/README.md section 1.1 in the repository for the full
explanation and troubleshooting.
