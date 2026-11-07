# Bản Python: chống trùng, tự tiếp tục và thống kê terminal

Các thay đổi chỉ áp dụng vào phần lập lịch/lưu tiến độ của `crawler.py`; giữ cách mở Chrome, stealth, xác minh thủ công đang dùng. Không cần extension cho các lệnh trong tài liệu này.

## Cập nhật mà giữ tiến độ

Dừng bản cũ bằng Ctrl+C, đợi xuất dữ liệu xong, rồi cập nhật mã tại thư mục đang dùng. Giữ nguyên `data/` gồm DB SQLite và profile trình duyệt. Không chạy hai bản crawler đồng thời trên cùng DB. Mã tự bổ sung index cần thiết cho DB cũ; không xóa hay đặt lại dữ liệu công ty/trạng thái tác vụ.

Nếu dùng DB ở đường dẫn riêng từ trước, phải truyền đúng `--db` đó. Chuyển sang thư mục chạy khác mà không mang theo data sẽ tạo DB mới, không thể nhận ra dữ liệu đã thu thập ở DB cũ.

## Chạy liên tục và tự chọn trang tiếp theo

Trong thư mục `sequential-crawler`, dùng:

```powershell
python crawler.py run --browser --browser-channel chrome --stealth --delay 8 --jitter 2 --stats-every 15
```

Hoặc mở `chay_python.bat` trên Windows sau khi đã cài thư viện. File này chạy không giới hạn số trang; Ctrl+C để dừng an toàn.

- DB đã có hàng đợi: tự chọn tác vụ pending tiếp theo. Không quay lại trang chủ chỉ vì bỏ qua --start.
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

36 kiểm thử Python, gồm tiếp tục sau đóng/mở DB, bỏ qua trang công ty cũ, giữ nhãn seed có sẵn, không mở Chrome khi đã xong, thống kê trong lúc chờ và khóa giữa hai tiến trình. Các kiểm thử mới dùng HTML mẫu/khách mạng mô phỏng; không cần thu thập lại nguồn thật hoặc thay đổi cấu hình phiên Chrome đang hoạt động của bạn.
