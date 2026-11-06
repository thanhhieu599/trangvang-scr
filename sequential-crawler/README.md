# Bộ thu thập Trang Vàng Việt Nam

Python 3.10+. Dùng cho việc thu thập đã được chủ nguồn cho phép.

**Trạng thái ngày 06/11/2026:** đã vượt qua 7 kiểm thử tự động bằng dữ liệu mẫu. Đã truy cập được robots.txt và trang chủ bằng chương trình, xác minh HTML thật của lĩnh vực Hóa Chất, phân ngành 47910 và công ty Kemic. Chạy thử đầu cuối trang Kemic đã xuất đủ 5 trường trong sample/companies.csv và sample/companies.xlsx. Chưa chạy toàn bộ danh bạ, chưa bảo đảm mọi công ty có cùng cấu trúc. Yêu cầu curl ban đầu bị Cloudflare chặn, vì vậy khả năng truy cập có thể thay đổi; chương trình dừng nếu bị chặn thay vì vượt chặn.

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

Không dùng proxy xoay vòng, giả dấu vân tay, giải CAPTCHA tự động hoặc vượt chặn. User-Agent minh bạch. Kiểm tra robots.txt đầu phiên, theo crawl-delay/request-rate, tốc độ tối thiểu 3 giây/yêu cầu, mặc định 5 giây. Thử lại tối đa 4 lần với lỗi mạng/5xx. HTTP 401/403/429, dấu hiệu CAPTCHA/Cloudflare hoặc robots.txt không hợp lệ làm dừng. Chuyển hướng cũng dừng để kiểm tra, tránh truy cập nhầm nơi; chỉ thu thập cùng domain, không truy cập website ngoài của từng công ty.

Nếu vẫn bị chặn, cần chủ website cấp API, bản xuất dữ liệu hoặc cho phép IP/User-Agent của bạn. Tiếp tục cùng DB sau khi quyền truy cập đã được mở. Bộ này không bảo đảm vượt chống bot.

## Giới hạn cần xác minh trên nguồn thật

- Link lĩnh vực /gindex/, phân ngành /categories/, công ty /listings/ được suy ra từ URL bạn cung cấp.
- Bộ phân trang ưu tiên liên kết Tiếp/next, nếu không có thì chọn số trang kế tiếp nhỏ nhất, trong cùng category với tham số page/p/pageindex/pageIndex. Đã xác minh trang mẫu dùng ?page=2. Phân trang kiểu JavaScript hoặc cấu trúc khác cần sửa next_pages().
- Trang danh sách hiện ưu tiên tiêu đề h2.tvx-cn theo HTML thật đã kiểm tra (38 tiêu đề công ty trên trang mẫu), tránh lấy các liên kết quảng cáo ngoài khối danh sách. Trang không có cấu trúc này dùng fallback liên kết /listings/; cần đối chiếu nếu website thay đổi.
- Thông tin hiển thị bằng ảnh/JavaScript, ẩn phía sau nút, email bảo vệ không được giải mã hay suy đoán.
- Một công ty có nhiều loại Organization trong JSON-LD mà không khớp h1 sẽ cần kiểm tra selector thủ công để tránh chọn nhầm.
