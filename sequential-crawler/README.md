# Bộ thu thập Trang Vàng Việt Nam

Python 3.10+. Dùng cho việc thu thập đã được chủ nguồn cho phép.

**Trạng thái ngày 07/11/2026:** đã vượt qua 27 kiểm thử tự động và kiểm tra tích hợp Chromium thật trên trang mẫu. Chưa xác minh vượt chặn Cloudflare trên máy người dùng. Đã truy cập được robots.txt và trang chủ bằng chương trình, xác minh HTML thật của lĩnh vực Hóa Chất, phân ngành 47910 và công ty Kemic. Chạy thử đầu cuối trang Kemic đã xuất đủ 5 trường trong sample/companies.csv và sample/companies.xlsx. Chưa chạy toàn bộ danh bạ, chưa bảo đảm mọi công ty có cùng cấu trúc. Yêu cầu curl ban đầu bị Cloudflare chặn, vì vậy khả năng truy cập có thể thay đổi; chương trình dừng nếu bị chặn thay vì vượt chặn.

## Lựa chọn mới: extension trong Chrome đang dùng

Nếu Chrome mở thủ công truy cập được còn Playwright vẫn bị chặn, có thể thử bản `chrome-extension/`. Cài qua `chrome://extensions` → Developer mode → Load unpacked, chọn thư mục có manifest.json. Mở Trang Vàng rồi bấm biểu tượng extension để tự duyệt và xuất CSV, không cần Ctrl+S từng trang. Đọc [hướng dẫn extension](chrome-extension/README.md) và [kết quả nghiên cứu GitHub/Stack Overflow/tài liệu chính thức](RESEARCH.md).

Extension dùng IndexedDB riêng, không dùng DB SQLite của Python. Chưa kiểm chứng bản cài thực tế trong Chrome người dùng do môi trường kiểm thử cấm nạp unpacked extension. Không có cam kết vô hiệu hóa Cloudflare.

## Cài đặt

```sh
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest -v
```

## Chạy thử nhỏ trước

```sh
python crawler.py run --start "https://trangvangvietnam.com/listings/1187779161/hoa-chat-kemic-cong-ty-co-phan-kemic.html" --db data/smoke.sqlite --max-pages 1
```

Đối chiếu từng trường trong data/export/companies.xlsx với trang nguồn. Không coi bản ghi có review_required=True là đầy đủ. Thiếu thông tin được để trống, không suy đoán email hay số điện thoại. Trang thiếu tên được đánh dấu lỗi. Nếu không thu được thông tin, cần chỉnh parse_company() theo HTML thật đã được phép truy cập. Hàm này ưu tiên JSON-LD, microdata, liên kết tel/mailto trong khối chứa h1; không quét toàn trang để tránh nhầm thông tin quảng cáo.

Sau khi đối chiếu, dùng DB riêng để chạy từ đầu trang chủ:

```sh
python crawler.py run --start "https://trangvangvietnam.com/" --delay 5 --db data/full.sqlite --max-pages 20
python crawler.py status --db data/full.sqlite
```

Bỏ --max-pages hoặc đặt bằng 0 để xử lý toàn bộ hàng đợi. Chạy lại cùng lệnh và cùng DB để tiếp tục. --max-pages đếm số tác vụ trang thành công trong lần chạy này, gồm lĩnh vực/phân ngành/danh sách/chi tiết; không phải số công ty.

Chỉ một lĩnh vực:

```sh
python crawler.py run --start "https://trangvangvietnam.com/gindex/7/h%C3%B3a-ch%E1%BA%A5t" --db data/chem.sqlite
```

Chỉ một phân ngành:

```sh
python crawler.py run --start "https://trangvangvietnam.com/categories/47910/hoa-chat-san-xuat-nhap-khau-va-phan-phoi-hoa-chat.html" --db data/category.sqlite
```

Khi bắt đầu trực tiếp từ URL lĩnh vực/phân ngành, nhãn nguồn dùng URL đó. Chạy từ trang chủ lấy nhãn từ liên kết.

## Khi requests bị chặn: mở trình duyệt có giao diện

Cập nhật nhánh `codex/sequential-company-crawler`, mở terminal trong `sequential-crawler/`, cài thêm:

```sh
python -m pip install -r requirements-browser.txt
```

Dùng Google Chrome đã cài trên máy (có thể thay `chrome` bằng `msedge`):

```sh
python crawler.py run --browser --browser-channel chrome --delay 8 --max-pages 20
```

Nếu không có Chrome/Edge, cài Chromium của Playwright và chạy:

```sh
python -m playwright install chromium
python crawler.py run --browser --delay 8 --max-pages 20
```

Một cửa sổ trình duyệt riêng sẽ mở. **Giữ cửa sổ/tab này mở trong suốt lúc chạy**; mở website trong một Chrome khác không thay thế được phiên của chương trình. Khi gặp trang xác minh, terminal sẽ nhắc bạn hoàn tất thao tác trong cửa sổ đó. Chờ trang nội dung thật xuất hiện, quay lại terminal và nhấn Enter. Nhập `q` hoặc Ctrl+C để dừng. Trong lúc chờ Enter, vòng xử lý Playwright vẫn chạy để trang và bước xác minh tiếp tục tải. Nếu đóng tab/cửa sổ, chương trình dừng với thông báo rõ ràng và dọn các route trước khi đóng context. Trang “Sorry, you have been blocked” được nhận diện là từ chối truy cập và dừng ngay, không chờ Enter vô ích. Với trang có bước xác minh, mỗi lần tải chỉ nhắc một lần; nếu vẫn bị chặn, chương trình dừng và giữ tác vụ ở trạng thái pending. HTTP 401/429 làm dừng ngay. Không có giải CAPTCHA tự động; tùy chọn stealth/proxy được mô tả bên dưới.

Phiên trình duyệt lưu mặc định ở `data/browser-profile/`; các lần chạy sau dùng lại thư mục này. Nếu trước đó chạy với `--db` riêng, truyền **đúng đường dẫn DB cũ** để tiếp tục tiến độ đó. Đóng phiên chương trình trước khi chạy lại. Không dùng thư mục hồ sơ cá nhân của Chrome, không chạy hai tiến trình dùng chung profile. Thư mục này có cookie: không chia sẻ hoặc đưa lên GitHub. Dùng `--profile` nếu muốn chọn thư mục riêng khác.

Chạy trong terminal có thể nhập liệu và máy có giao diện màn hình; không dùng tác vụ nền cho chế độ này. Tốc độ vẫn có giới hạn, robots.txt vẫn được kiểm tra. Khi website từ chối truy cập hoặc robots.txt không cho phép, cần chủ nguồn cho phép truy cập/API. Việc mở Chrome không bảo đảm website sẽ cho phép thu thập.

Đã kiểm thử 27 trường hợp về trích xuất, tiến độ, xác minh, giới hạn tốc độ, robots, proxy và tùy chọn trình duyệt; kiểm tra tích hợp Chromium thật xác nhận stealth 2.x khởi tạo được và liên kết ẩn bị loại khỏi bản HTML trích xuất. Chưa kiểm chứng phiên xác minh Cloudflare thực tế trên máy người dùng.

## Tùy chọn stealth, proxy và chờ ngẫu nhiên

Cài phần mở rộng:

```sh
python -m pip install -r requirements-stealth.txt
python crawler.py run --browser --browser-channel chrome --stealth --delay 8 --jitter 2 --max-pages 20
```

`--stealth` áp dụng playwright-stealth 2.x trước khi mở trang và cờ AutomationControlled. Giữ User-Agent của phiên bản Chrome hiện tại; không gán chuỗi Chrome cũ hoặc đổi header ngẫu nhiên giữa các yêu cầu. Ngôn ngữ vi-VN, viewport 1366x768. Đây là thay đổi hành vi trình duyệt, không bảo đảm qua được Cloudflare.

`--jitter 2` thêm 0–2 giây vào thời gian nghỉ còn lại giữa các lần bắt đầu điều hướng; không giảm Crawl-delay. Khi thời gian tải trang dài hơn delay, phần delay đã được đáp ứng trong lúc chờ tải. Trong chế độ browser, các liên kết có CSS/thuộc tính làm ẩn được loại khỏi bản sao HTML; liên kết ở dưới màn hình nhưng có bố cục vẫn được giữ. Đây không phải cơ chế phát hiện mọi loại honeypot. Chế độ HTTP không có lọc theo CSS.

### Proxy của bạn

Cấu hình URL proxy trong biến môi trường tại máy bạn; không gửi thông tin đăng nhập lên chat hoặc commit vào GitHub. Ví dụ PowerShell với các giá trị **thay thế**:

```powershell
$env:TRANGVANG_PROXY = "http://USER:PASSWORD@HOST:PORT"
python crawler.py run --browser --browser-channel chrome --stealth --proxy-env TRANGVANG_PROXY --delay 8 --jitter 2 --max-pages 20
```

Trên bash dùng `export TRANGVANG_PROXY='http://USER:PASSWORD@HOST:PORT'`. Mã hóa URL các ký tự đặc biệt trong username/password (ví dụ @ thành %40). Hỗ trợ HTTP/HTTPS có xác thực hoặc SOCKS5 không xác thực. Proxy phải do bạn cung cấp; dự án không kèm dịch vụ proxy.

Nếu dùng nhà cung cấp proxy có cổng xoay IP, nên chọn chế độ **sticky session** để IP ổn định trong phiên xác minh. Chương trình dùng một endpoint trong một lần chạy, không tự đổi IP khi gặp 403/429 và không có pool proxy nội bộ. Thay endpoint/phiên proxy ở nhà cung cấp rồi chạy lại nếu cần; không có bảo đảm việc đổi IP sẽ hết chặn. Profile mặc định được tách theo cấu hình proxy, không trộn với phiên truy cập trực tiếp. Cookie cũ có thể mất hiệu lực khi IP thay đổi.

### Headless

Chỉ thêm `--headless` khi đã kiểm tra truy cập ổn định. Chế độ này dừng ngay khi gặp trang chặn vì không có cửa sổ để bạn xác minh. Khi dừng, bỏ `--headless` rồi chạy lại cùng DB/profile để kiểm tra. Không dùng `networkidle` vì trang có quảng cáo có thể không bao giờ hết kết nối; chương trình chờ DOM và phần tử nội dung.

Mặc định vẫn có giao diện để bạn nhìn thấy lỗi. Không mô phỏng chuột ngẫu nhiên hoặc mua dịch vụ giải CAPTCHA trong bản này. Proxy chưa được kiểm tra trên dịch vụ thật vì chưa có endpoint do người dùng cấu hình; kiểm thử chỉ xác minh cách cấu hình và tách thông tin đăng nhập.

## Dữ liệu và tiến độ

- SQLite chứa hàng đợi, trạng thái pending/done/error, dữ liệu công ty, quan hệ công ty với nhiều ngành.
- Duyệt theo chiều sâu: lĩnh vực → phân ngành → công ty từng trang → trang tiếp theo → phân ngành tiếp theo → lĩnh vực tiếp theo.
- Khóa công ty lấy ID trong /listings/; gặp lại sẽ bổ sung quan hệ ngành và không tải lại trang chi tiết.
- CSV UTF-8 BOM và XLSX: name, address, phones, emails, websites, source_url, collected_at (UTC), sectors, categories, review_required.
- HTML đã tải lưu cạnh DB trong html/ để đối chiếu; log nằm cạnh DB.
- CSV/XLSX được xuất khi hoàn tất hoặc tạm dừng bằng Ctrl+C. Nếu tiến trình bị kill cưỡng bức, có thể xuất lại từ SQLite.
- Mỗi DB chỉ chạy một tiến trình. Muốn thu thập lại thông tin đã hoàn tất, dùng DB mới. Không có cơ chế tự cập nhật định kỳ trong phiên bản này.

```sh
python crawler.py export --db data/full.sqlite --out data/export
python crawler.py status --db data/full.sqlite
python crawler.py retry-errors --db data/full.sqlite
python crawler.py run --db data/full.sqlite
```

retry-errors chỉ đưa tác vụ lỗi về pending; sau đó chạy run. Lỗi chặn giữ nguyên pending và dừng toàn phiên. Khi chưa còn pending, vẫn phải kiểm tra status để bảo đảm không còn error trước khi coi đợt thu thập hoàn tất.

## Quy tắc truy cập

Stealth và proxy là tùy chọn; không có bộ giải CAPTCHA tự động và không tự thử lại vô hạn khi bị chặn. Chế độ HTTP dùng User-Agent AuthorizedDirectoryCollector/1.0; chế độ browser dùng trình duyệt thông thường với hồ sơ riêng. Kiểm tra robots.txt đầu phiên, theo crawl-delay/request-rate, tốc độ tối thiểu 3 giây/yêu cầu, mặc định 5 giây. Thử lại tối đa 4 lần với lỗi mạng/5xx. Chế độ HTTP dừng ở HTTP 401/403/429 hoặc dấu hiệu CAPTCHA/Cloudflare. Chế độ browser cho phép xác minh thủ công một lần khi gặp trang chặn; nếu vẫn bị chặn thì dừng. robots.txt không hợp lệ làm dừng ở cả hai chế độ. Chuyển hướng cũng dừng để kiểm tra, tránh truy cập nhầm nơi; chỉ thu thập cùng domain, không truy cập website ngoài của từng công ty.

Nếu vẫn bị chặn, cần chủ website cấp API, bản xuất dữ liệu hoặc cho phép IP/User-Agent của bạn. Tiếp tục cùng DB sau khi quyền truy cập đã được mở. Bộ này không bảo đảm vượt chống bot.

## Giới hạn cần xác minh trên nguồn thật

- Link lĩnh vực /gindex/, phân ngành /categories/, công ty /listings/ được suy ra từ URL bạn cung cấp.
- Bộ phân trang ưu tiên liên kết Tiếp/next, nếu không có thì chọn số trang kế tiếp nhỏ nhất, trong cùng category với tham số page/p/pageindex/pageIndex. Đã xác minh trang mẫu dùng ?page=2. Phân trang kiểu JavaScript hoặc cấu trúc khác cần sửa next_pages().
- Trang danh sách hiện ưu tiên tiêu đề h2.tvx-cn theo HTML thật đã kiểm tra (38 tiêu đề công ty trên trang mẫu), tránh lấy các liên kết quảng cáo ngoài khối danh sách. Trang không có cấu trúc này dùng fallback liên kết /listings/; cần đối chiếu nếu website thay đổi.
- Thông tin hiển thị bằng ảnh/JavaScript, ẩn phía sau nút, email bảo vệ không được giải mã hay suy đoán.
- Một công ty có nhiều loại Organization trong JSON-LD mà không khớp h1 sẽ cần kiểm tra selector thủ công để tránh chọn nhầm.
