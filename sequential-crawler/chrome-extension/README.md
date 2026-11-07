# Thu thập trong Chrome đang sử dụng

Đây là một chế độ khác với `crawler.py`: chạy dưới dạng extension Manifest V3 trong Chrome thông thường của bạn. Extension dùng tab và phiên hiện tại, tự duyệt lĩnh vực → phân ngành → danh sách → công ty, không mở Chrome bằng Playwright/CDP. Không cần lưu HTML thủ công hoặc bấm thu thập từng công ty.

## Cài và chạy

1. Giải nén ZIP repository. Giữ nguyên thư mục `sequential-crawler/chrome-extension`.
2. Mở Chrome bình thường, vào `chrome://extensions`.
3. Bật **Developer mode / Chế độ dành cho nhà phát triển** ở góc phải.
4. Chọn **Load unpacked / Tải tiện ích đã giải nén**, chọn đúng thư mục `chrome-extension` có file `manifest.json`.
5. Mở Trang Vàng bằng chính Chrome đó, tới trang chủ (toàn bộ lĩnh vực), một URL `/gindex/` (một lĩnh vực), hoặc `/categories/` (một phân ngành). Kiểm tra trang đang xem truy cập được.
6. Bấm biểu tượng mảnh ghép của Chrome → **Trang Vang - Sequential Collector**. Đặt số trang chạy thử (mặc định 20), bấm **Bắt đầu từ tab này**.
7. Extension mở robots.txt trước rồi quay về luồng thu thập. Giữ tab đó mở và không điều hướng thủ công trong lúc đang chạy. Đóng popup vẫn chạy được.
8. Mở popup để xem tiến độ, tạm dừng, tiếp tục hoặc **Xuất CSV**. Excel đọc được file UTF-8 BOM này.

Nếu Chrome do cơ quan quản lý không cho phép tải extension ngoài, cần quản trị viên cho phép; công cụ không thay đổi chính sách quản trị.

## Tốc độ và tiếp tục

- Chỉ một tab, mỗi lần một trang. Khoảng nghỉ tối thiểu 30 giây, cộng 0–5 giây, tuân theo Crawl-delay nếu dài hơn. Tốc độ lý thuyết tối đa khoảng 120 trang/giờ, chưa tính thời gian tải. Đây là lựa chọn ưu tiên giữ ổn định lịch chạy Manifest V3, không phải chế độ thu thập nhanh.
- 20 là số trang nội dung (có cả trang lĩnh vực/phân ngành/danh sách), không phải 20 công ty. Chọn 0 để không giới hạn, rồi bấm Tiếp tục nếu đã có phiên.
- Hết danh sách công ty của trang hiện tại sẽ sang trang tiếp theo **trong cùng phân ngành**, sau đó mới sang phân ngành kế tiếp. Công ty đã gặp chỉ bổ sung quan hệ ngành, không tải lại trang chi tiết.
- Hàng đợi và dữ liệu lưu ở IndexedDB của extension trên máy, không ở biến nhớ của service worker. Khi Chrome mở lại, chọn tab Trang Vàng rồi bấm Tiếp tục. Nếu cần, extension đưa tab về URL đang chờ.
- Có hàng đợi cũ thì dùng **Tiếp tục**, không bắt đầu một đợt mới. Đổi giới hạn trang/khoảng nghỉ rồi Tiếp tục sẽ áp dụng giá trị mới.
- Tiến độ và dữ liệu extension độc lập với SQLite của Python; bản này chưa có nhập/chuyển đổi tiến độ giữa hai chế độ.
- Gỡ extension hoặc xóa dữ liệu extension sẽ mất cơ sở dữ liệu cục bộ: xuất CSV trước. Cập nhật bản giải nén tại cùng đường dẫn rồi bấm Reload trên chrome://extensions; không gỡ cài đặt khi cần giữ dữ liệu.

## Theo dõi trực tiếp

Popup tự cập nhật mỗi 2 giây khi đang mở. Bấm **Mở bảng tiến độ** để giữ một tab riêng hiển thị thông tin trong lúc tab Trang Vàng tự chuyển trang. Bảng này ghi nhớ tab nguồn; nút Tiếp tục vẫn điều khiển tab thu thập, không điều hướng tab bảng tiến độ.

Hiển thị: tổng công ty trong kho; số công ty mới và số lượt bỏ qua đã có trong lượt chạy; ngành/phân ngành và URL đang xử lý; số trang chờ; thời gian chờ lượt tiếp theo; tên, địa chỉ, SĐT, email, website của công ty vừa xử lý; 50 sự kiện gần nhất (đang tải/đã lưu/bỏ qua/dừng). Số mới và số bỏ qua của lượt được đặt về 0 khi bấm Bắt đầu hoặc Tiếp tục; tổng kho không bị đặt lại. Bỏ qua tính theo lượt gặp trong hàng đợi, không phải số công ty duy nhất. Trang đã done không vào hàng đợi lần nữa nên không tăng số bỏ qua.

### Cơ chế không tải lại công ty đã lưu

- Khóa công ty là phần `/listings/<ID số>`, độc lập slug/tên công ty. Hai URL khác tên nhưng cùng ID vẫn nhận diện là một công ty.
- Trước khi điều hướng tới trang chi tiết, kiểm tra `companies` trong IndexedDB. Nếu đã có, không mở lại trang: bổ sung quan hệ ngành, đánh dấu tác vụ done và ghi nhật ký bỏ qua.
- Mỗi tác vụ có khóa riêng và trạng thái pending/done. Ghi bản ghi công ty, đánh dấu done và cập nhật bộ đếm trong cùng một giao dịch IndexedDB; giao dịch thất bại sẽ không lưu nửa chừng.
- Đóng/mở Chrome rồi tiếp tục vẫn dùng dữ liệu cũ nếu cùng extension/profile và kho chưa bị xóa. Dữ liệu không chia sẻ tự động giữa profile/máy hoặc với Python.
- Nếu tắt máy trước lúc giao dịch hoàn tất, tác vụ đang dở có thể tải lại; khóa duy nhất ngăn tạo hai bản ghi cùng ID. Đây không phải cam kết mỗi URL chỉ được tải đúng một lần trong mọi sự cố.
- Công ty đã lưu nhưng thiếu trường (review_required) vẫn được coi là đã có. Chưa có chế độ tự cập nhật trường cũ; dữ liệu website thay đổi không tự ghi đè. Hai ID nguồn khác nhau không bị gộp chỉ vì trùng tên/điện thoại.

## Dữ liệu và quyền

Lấy name, address, phones, emails, websites, source_url, collected_at, sectors, categories, review_required. Thiếu trường được để trống và đánh dấu review_required. Không đoán email, không truy cập website bên ngoài của công ty. Dữ liệu công ty chưa chắc cùng mẫu HTML, cần đối chiếu sau khi chạy thử. CSV trung hòa công thức Excel; số bắt đầu bằng + có thể có dấu nháy để giữ dạng văn bản.

Quyền extension: chỉ hai hostname Trang Vàng, scripting để đọc DOM, alarms để chạy lịch và unlimitedStorage để giữ cơ sở dữ liệu lớn. Không yêu cầu quyền đọc cookie, proxy, debugger, hoặc truy cập mọi website. Không gửi dữ liệu tới máy chủ bên thứ ba. Extension dùng phiên Chrome hiện có thông qua điều hướng bình thường, không sao chép cookie sang Python.

Khi phát hiện trang chặn/CAPTCHA hoặc không nhận diện được cấu trúc trang, extension tạm dừng và giữ hàng đợi. Chỉ bấm Tiếp tục khi tab đã truy cập được. Extension không vô hiệu hóa Cloudflare, không giải CAPTCHA tự động và không bảo đảm luôn tránh bị chặn. Không tích hợp proxy trong extension; những tùy chọn đó vẫn chỉ có trong chế độ Python.

## Kiểm thử và giới hạn xác minh

- 8 kiểm thử Node cho URL, nhận diện cấp ngành, khóa chống trùng, robots longest-match/wildcard và CSV an toàn.
- Harness Chromium kiểm tra trích xuất DOM, IndexedDB, toàn bộ luồng trên trang mẫu, phân trang trước phân ngành kế tiếp, chống trùng/quan hệ ngành, nạp lại dữ liệu và tải CSV. **API Chrome được mô phỏng trong harness**, không phải thử extension đã cài.
- Đã đối chiếu bộ trích xuất trên HTML thật đã lưu của Kemic (đủ 5 trường), trang danh sách (38 tiêu đề công ty) và lĩnh vực Hóa Chất.
- Môi trường phát triển cấm tải unpacked extension theo chính sách quản trị (`Loading of unpacked extensions is disabled by the administrator`), nên chưa kiểm chứng bản extension được cài thực tế hoặc việc vượt chặn Trang Vàng trong Chrome người dùng. Cần chạy thử trên máy bạn.

```sh
node tests/core.test.js
# Python + Playwright (cài requirements-browser.txt ở thư mục cha):
python -m playwright install chromium
python tests/browser_harness.py
```

Nếu cần dùng Chromium đã cài trên máy cho harness, đặt biến `CRAWLER_CHROMIUM_EXECUTABLE` trỏ đến file thực thi. Harness dùng trang mẫu và mô phỏng API Chrome, không crawl nguồn thật.
