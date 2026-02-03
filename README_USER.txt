============================================
  Product Collector - User Guide
============================================

[Requirements]
- Windows 10/11
- Chrome browser

[First Time Setup]
1. Double-click "install_browser.bat"
   - This installs the browser component
   - Only needed once

2. Run "ProductCollector.exe"

[How to Use]
1. Enter a category URL (not a product URL)
   - Musinsa: https://www.musinsa.com/category/...
   - Naver: https://brand.naver.com/.../category/...

2. Set collection range (optional)
   - Check "전체 수집" for all products
   - Or specify range: Start ~ End
     Example: 1 ~ 100 (products 1-100)
     Example: 201 ~ 300 (products 201-300)

3. Click "Start Collection"

4. Output file: output/{site}_products_YYYYMMDD_HHMMSS.xlsx

[Auto-Save Feature]
- Automatically saves every 10 products
- Auto-save file: output/{site}_autosave_진행중.xlsx
- Single file that gets overwritten with latest data
- If program crashes, check auto-save file for progress

[Resume Collection]
If collection was interrupted:
1. Check auto-save file (e.g., musinsa_autosave_진행중.xlsx)
2. Open Excel file to see how many products were saved
3. Rename auto-save file to keep it (e.g., musinsa_1-150.xlsx)
4. Restart program
5. Set range starting from next product
   (e.g., Start: 151, End: 300)
6. Manually merge Excel files after completion

[Troubleshooting]
- Windows Defender warning:
  Click "More info" -> "Run anyway"

- Browser error:
  Run install_browser.bat again

- Collection not starting:
  Make sure you entered a category URL,
  not a product page URL

[Support]
For issues, contact: support@example.com

============================================
  Version 2.6 (Updated: 2026-01-30)
============================================
