# Đối chiếu tài liệu chống chặn — 07/11/2026

Đã đọc bài iProxy người dùng gửi và tra cứu GitHub, Stack Overflow, tài liệu Cloudflare và Chrome. Không coi các tuyên bố marketing về proxy/stealth là bảo đảm kỹ thuật, không sao chép mã không rõ nguồn gốc.

## Kết quả và cách áp dụng

1. **Giữ phiên trình duyệt nhất quán.** Cloudflare liệt kê thay đổi User-Agent, thiếu cookie/DOM storage và mạng không ổn định là nguyên nhân xác minh thất bại; cơ chế challenge còn có thể thất bại khi IP thực hiện xác minh khác IP lúc nhận challenge. Vì vậy không tự đổi UA/IP theo từng trang trong cùng phiên.
   - https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/
   - https://developers.cloudflare.com/cloudflare-challenges/concepts/how-challenges-work/

2. **Stealth không đồng nghĩa qua được challenge.** Tài liệu Cloudflare không hỗ trợ các framework tự động hóa để giải production challenge. Các thảo luận Stack Overflow có báo cáo thêm cookies/UA/stealth vẫn lỗi. Đây là kinh nghiệm trường hợp riêng, không phải kiểm chứng trên Trang Vàng; không dùng ý kiến cộng đồng thay cho tài liệu chính thức.
   - https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/
   - https://stackoverflow.com/questions/79000090/playwright-cannot-bypass-cloudflare-bot-detection-even-adding-cookies-and-user-a
   - https://stackoverflow.com/questions/79995776/why-does-selenium-playwright-keep-getting-detected-by-cloudflare-even-with-steal/79995990

3. **Đúng phiên Chrome là một hướng đáng kiểm tra.** Báo cáo GitHub có trường hợp phiên Playwright tách biệt bị Cloudflare chặn trong khi phiên Chrome người dùng vẫn hoạt động. Kết hợp với thông tin người dùng trong cuộc hội thoại này, quyết định thử một extension dùng tab Chrome hiện tại. Đây là suy luận thiết kế, không chứng minh nguyên nhân chặn và không bảo đảm hết chặn.
   - https://github.com/openai/codex/issues/22346

4. **Lịch chạy và lưu tiến độ theo Manifest V3.** Không dựa vào biến nhớ hoặc setTimeout dài trong service worker. Lưu hàng đợi vào IndexedDB và dùng Chrome alarms; lịch mỗi trang tối thiểu 30 giây để phù hợp giới hạn của alarms. Đọc DOM qua scripting, không cần cookie/debugger permission.
   - https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
   - https://developer.chrome.com/docs/extensions/reference/api/alarms
   - https://developer.chrome.com/docs/extensions/reference/api/scripting

5. **Áp dụng giới hạn tốc độ, tránh link ẩn và ngừng lặp lại khi lỗi.** Extension một tab, có khoảng nghỉ, lọc liên kết không hiển thị, dừng ở CAPTCHA/trang chặn. Không thêm chuột ngẫu nhiên chỉ để tạo cảm giác có tác dụng; chưa có bằng chứng nó giải quyết lỗi của người dùng. Giữ JavaScript/cookie hoạt động bình thường, không làm theo gợi ý tắt chúng trong bài quảng cáo vì challenge phụ thuộc các khả năng đó.

## Phạm vi đã làm

- Python giữ tùy chọn stealth/proxy/headless và quản lý phiên đã có. Sửa ưu tiên phân trang để hết trang của cùng phân ngành trước khi sang phân ngành khác.
- Thêm `chrome-extension/`: tự duyệt trong Chrome thường, đọc trang hiện có, chống trùng và lưu tiến độ tại máy, xuất CSV.
- Không tích hợp API giải CAPTCHA, không mua proxy, không cấu hình dịch vụ bên ngoài. Chưa thử proxy thật hoặc chứng minh vượt Cloudflare trên máy người dùng.
- Môi trường phát triển cấm nạp extension ngoài theo chính sách quản trị; đã kiểm thử bộ trích xuất trên DOM thật và kiểm thử controller với API Chrome mô phỏng. Phải phân biệt kết quả này với kiểm thử extension đã cài vào Chrome người dùng.
