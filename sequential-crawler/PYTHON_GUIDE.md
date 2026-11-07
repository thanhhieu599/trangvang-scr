# Bản Python: chống trùng, tự tiếp tục và thống kê terminal

Các thay đổi chỉ áp dụng vào phần lập lịch/lưu tiến độ của `crawler.py`; giữ cách mở Chrome, stealth, xác minh thủ công đang dùng. Không cần extension cho các lệnh trong tài liệu này.

## Nhập danh mục trực tiếp trong terminal — cách dùng khuyên dùng

Mở `chay_python.bat`, hoặc gõ:

```powershell
python crawler.py select
```

Gõ `python crawler.py` không có tham số cũng mở chế độ này. `select` tự dùng Chrome đã cài và stealth. Chương trình hiện:

```text
=== QUÉT DANH MỤC DO BẠN CHỌN ===
Dán link danh mục [Enter = tiếp tục danh mục gần nhất; q = thoát]:
```

Dán link phân ngành `/categories/...` hoặc lĩnh vực `/gindex/...` rồi Enter. Nếu trước đó đã chọn danh mục, Enter khi để trống sẽ tiếp tục chính danh mục gần nhất. Nhập q để thoát. Không cần tạo file HTML, extension hay sửa mã nguồn.

Ví dụ link: `https://trangvangvietnam.com/categories/47910/hoa-chat-san-xuat-nhap-khau-va-phan-phoi-hoa-chat.html`.

Chỉ quét danh mục đã chọn, tự qua các trang danh sách và từng công ty. Nếu nhập một lĩnh vực /gindex/, tự quét các phân ngành thuộc lĩnh vực đó. Hàng đợi của các ngành khác từ lần trước được giữ lại nhưng không xen vào đợt này. Công ty cũ trong cùng SQLite vẫn được kiểm tra theo ID và bỏ qua tải lại, kể cả đã thu thập ở ngành khác.

Khi chọn cùng danh mục ở lần sau, tiếp tục các tác vụ chưa xong. Danh mục đã xử lý hết sẽ không tự tải lại. Danh mục được lưu trong settings; run/resume/status/retry-errors/export không truyền URL sau đó sẽ áp dụng cho danh mục gần nhất. Dùng --start trong lệnh run sẽ bỏ lựa chọn phạm vi và quay lại cơ chế hàng đợi chung cũ.

Muốn nhập link ngay trong lệnh thay vì đợi câu hỏi:

```powershell
python crawler.py select --category "https://trangvangvietnam.com/categories/47910/hoa-chat-san-xuat-nhap-khau-va-phan-phoi-hoa-chat.html"
```

CSV/Excel chỉ chứa công ty thuộc danh mục đã chọn, mặc định ở `data/export/categories_47910/` (hoặc `data/export/gindex_7/` nếu chọn lĩnh vực). Các bản ghi khác vẫn giữ trong SQLite. Tham số --out ghi đè thư mục xuất nếu cần. Thống kê Tổng kho là tổng công ty trong DB dùng chung; số tác vụ chờ/xong/lỗi chỉ tính trong danh mục đang chọn.

## Vì sao log trông như đứng yên?

Trong log gửi ngày 07/11/2026, đã lưu 69 công ty rồi xuất hiện “Cần thao tác thủ công” lúc 15:09:10. Sau đó chương trình chờ người dùng xác minh/Enter, trong khi thống kê vẫn in đều; đó không phải vòng lặp tải lại công ty.

Bản mới in rõ trạng thái NGHỈ GIỮA HAI LƯỢT / ĐANG TẢI / ĐỢI NỘI DUNG TRANG / CHỜ XÁC MINH và thời gian còn lại. Mặc định --verify-timeout 120: hết 120 giây chờ xác minh sẽ dừng có lưu dữ liệu. Đặt 0 chỉ khi chủ động muốn chờ vô hạn. Không tự bỏ qua xác minh để tiếp tục gửi yêu cầu.

--page-timeout 45 giới hạn thời gian điều hướng chính; sau đó đợi phần tử nội dung tối đa 15 giây. Timeout tải/nội dung được đánh dấu error và chuyển sang tác vụ khác trong danh mục. Trang lỗi được giữ để thử lại bằng retry-errors. Chặn truy cập/CAPTCHA vẫn tạm dừng toàn lượt; không coi là lỗi tải thông thường để lặp truy cập.

Bộ phát hiện cũng phân biệt trang công ty thật có form reCAPTCHA với trang chặn: chỉ thấy chuỗi g-recaptcha hoặc script Cloudflare trong trang đã có nội dung công ty không còn tự động đòi xác minh. Không thể kết luận trường hợp nào đã xảy ra chỉ từ log cũ.

File .bat dùng khoảng nghỉ 5 giây cộng 0–1 giây (vẫn theo Crawl-delay nếu cao hơn). Tốc độ thực tế tùy thời gian tải; không có bảo đảm số công ty/phút.

## Cập nhật mà giữ tiến độ

Dừng bản cũ bằng Ctrl+C, đợi xuất dữ liệu xong, rồi cập nhật mã tại thư mục đang dùng. Giữ nguyên `data/` gồm DB SQLite và profile trình duyệt. Không chạy hai bản crawler đồng thời trên cùng DB. Mã tự bổ sung index cần thiết cho DB cũ; không xóa hay đặt lại dữ liệu công ty/trạng thái tác vụ.

Nếu dùng DB ở đường dẫn riêng từ trước, phải truyền đúng `--db` đó. Chuyển sang thư mục chạy khác mà không mang theo data sẽ tạo DB mới, không thể nhận ra dữ liệu đã thu thập ở DB cũ.

## Chạy liên tục và tự chọn trang tiếp theo

Trong thư mục `sequential-crawler`, dùng:

```powershell
python crawler.py run --browser --browser-channel chrome --stealth --delay 5 --jitter 1 --stats-every 15
```

File `chay_python.bat` hiện mở chế độ nhập danh mục ở trên. Các lệnh run/resume dùng hàng đợi đang được chọn, mặc định không giới hạn số trang; Ctrl+C để dừng an toàn.

- DB đã có hàng đợi: tự chọn tác vụ pending tiếp theo trong phạm vi được chọn (nếu có). Không quay lại trang chủ chỉ vì bỏ qua --start.
- DB mới: bắt đầu ở trang chủ, duyệt lĩnh vực → phân ngành → công ty của trang hiện tại → trang danh sách tiếp theo trong cùng phân ngành → phân ngành tiếp theo → lĩnh vực tiếp theo.
- Tác vụ done không được chạy lại. Công ty cùng ID nhưng nằm ở ngành khác được bỏ qua tải chi tiết và chỉ bổ sung quan hệ ngành.
- Chỉ khởi tạo Chrome khi có tác vụ thật sự cần tải mạng. Nếu toàn bộ hàng đợi đã xong hoặc các tác vụ còn lại chỉ là công ty đã có, không cần mở Chrome.
- Chạy lại cùng lệnh sau khi dừng sẽ tiếp tục. Khi muốn chắc chắn chỉ tiếp tục DB cũ mà không khởi tạo đợt mới, dùng:

```powershell
python crawler.py resume --browser --browser-channel chrome --stealth --delay 8 --jitter 2 --stats-every 15
```

Lệnh resume báo lỗi nếu DB chưa có hàng đợi. Nó không nhận --start. Nếu muốn bắt đầu từ phân ngành cụ thể trong lần chạy mới:

```powershell
python crawler.py run --start "https://trangvangvietnam.com/categories/47910/hoa-chat-san-xuat-nhap-khau-va-phan-phoi-hoa-chat.html" --browser --browser-channel chrome --stealth --stats-every 15
```

Nếu có hàng đợi cũ, các tác vụ vẫn được chọn theo thứ tự ưu tiên đã lưu; --start không xóa hay thay thế hàng đợi. Một URL bắt đầu đã có trong hàng đợi được sử dụng lại thay vì thêm seed với nhãn ngành khác.

Muốn chạy thử 20 tác vụ, thêm `--max-pages 20`. Mặc định là 0 = không giới hạn; đạt giới hạn sẽ dừng có lưu tiến độ, không tự mở thêm một lượt 20 mới. Con số này tính cả các cấp trang và tác vụ bỏ qua đã có, không chỉ số công ty mới.

## Thống kê trong terminal

Sau mỗi tác vụ sẽ in tên ngành/phân ngành, công ty đã lưu hoặc đã có, tổng kho, công ty mới/bỏ qua của lượt, tác vụ chờ/lỗi. Lưu công ty mới sẽ in đủ tên, địa chỉ, SĐT, email và website; trường thiếu để dấu -.

Mỗi 15 giây còn có dòng THỐNG KÊ: tổng kho, mới/bỏ qua của lượt, tác vụ đã xong/chờ/lỗi, thời gian chạy, tốc độ công ty mới/phút, ngành/phân ngành và URL đang xử lý. Dòng này vẫn xuất hiện trong khi trình duyệt chờ tải/xác minh. Chỉ luồng chính điều khiển Playwright; luồng thống kê đọc SQLite qua một kết nối riêng chỉ đọc.

Tùy chỉnh khoảng cập nhật bằng --stats-every N (1–3600 giây); --stats-every 0 tắt thống kê định kỳ nhưng vẫn in sau mỗi tác vụ. Khi đang nhập xác minh, thống kê có thể xuất hiện trong terminal; bạn vẫn nhập Enter/q bình thường.

Log đồng thời được lưu cạnh DB, ví dụ `data/crawler.log`. Dữ liệu CSV/Excel được xuất khi hoàn tất, đạt giới hạn, gặp chặn hoặc dừng bằng Ctrl+C. Nếu kill cưỡng bức, dữ liệu đã commit vẫn ở SQLite; chạy export để xuất lại.

```powershell
python crawler.py status
python crawler.py export
```

status còn hiển thị next_url, chính là trang đang chờ được chọn tiếp. Nếu pending đã hết nhưng còn error, chương trình báo rõ còn lỗi và không coi là hoàn tất toàn bộ:

```powershell
python crawler.py retry-errors
python crawler.py resume --browser --browser-channel chrome --stealth --stats-every 15
```

## Cơ chế chống trùng và giới hạn

- PRIMARY KEY `companies.company_id` lấy ID số trong /listings/; không dùng tên công ty để nhận dạng.
- UNIQUE `tasks.task_key` giữ mỗi nhiệm vụ, và status pending/done/error giữ tiến độ. Bảng memberships có UNIQUE để không lặp quan hệ ngành.
- Tra companies trước khi tải; đã có thì không yêu cầu trang chi tiết. Ghi công ty, quan hệ ngành và trạng thái done trong cùng giao dịch.
- Khóa file theo DB ngăn hai tiến trình crawler.py mới chạy đồng thời trên cùng DB. Khóa do hệ điều hành quản lý, tự nhả khi tiến trình chết. File .lock còn nằm trên đĩa là bình thường; không phải dấu hiệu bị khóa vĩnh viễn. Bản cũ không biết cơ chế khóa này, vì vậy đóng tất cả bản cũ trước khi dùng bản mới.
- Mất điện khi đang tải và chưa commit có thể khiến URL đang dở được tải lại; khóa duy nhất bảo vệ bản ghi cùng ID. Không bảo đảm đúng một lần tải mạng trong mọi sự cố.
- Công ty đã lưu dù thiếu trường vẫn được bỏ qua; chưa có tự cập nhật dữ liệu cũ. Không chia sẻ chống trùng giữa hai DB, profile/máy khác nhau hoặc với extension. Hai ID Trang Vàng khác nhau được coi là hai bản ghi.

## Kiểm thử

48 kiểm thử Python, gồm tiếp tục sau đóng/mở DB, bỏ qua trang công ty cũ, giữ nhãn seed có sẵn, không mở Chrome khi đã xong, thống kê trong lúc chờ và khóa giữa hai tiến trình. Các kiểm thử mới dùng HTML mẫu/khách mạng mô phỏng; không cần thu thập lại nguồn thật hoặc thay đổi cấu hình phiên Chrome đang hoạt động của bạn.
