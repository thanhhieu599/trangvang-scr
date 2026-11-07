# Ver 2.0 — tối ưu tốc độ, giữ tiến độ và chống trùng

V2 được phát hành trên nhánh riêng `codex/python-v2-fast`. Nhánh `codex/sequential-company-crawler` vẫn giữ bản v1 đang hoạt động của bạn.

## Cách dùng

1. Dừng v1 bằng Ctrl+C và đợi xuất dữ liệu/đóng chương trình xong.
2. Giải nén v2. Muốn tiếp tục dữ liệu cũ, sao chép **toàn bộ thư mục data/** từ v1 sang `sequential-crawler/data/` của v2 khi các chương trình dùng DB đã đóng. Nên giữ một bản sao dự phòng trước lần chạy v2 đầu tiên.
3. Mở `chay_v2.bat`, hoặc chạy trong thư mục sequential-crawler:

```powershell
python crawler_v2.py select
```

Dán link danh mục khi terminal hỏi. Enter khi bỏ trống sẽ tiếp tục danh mục gần nhất. Không cần extension hoặc file HTML. Lệnh trên mặc định dùng Chrome + stealth; nếu máy chưa cài thư viện, cài bằng `python -m pip install -r requirements-stealth.txt`.

Tiếp tục phiên gần nhất không cần nhập lại:

```powershell
python crawler_v2.py resume
```

Nếu trước đây bạn dùng --db/--profile riêng, giữ đúng các đường dẫn đó. Không chạy v1 và v2 đồng thời trên cùng DB/profile. Không xóa file .sqlite-wal/.sqlite-shm nếu chúng còn tồn tại; khi di chuyển cần mang cả thư mục và chỉ di chuyển sau khi tất cả ứng dụng dùng DB đã đóng.

## Giữ nguyên những gì

- Nhập danh mục trong terminal; chỉ quét đúng danh mục/lĩnh vực đã chọn.
- Tự duyệt từng công ty, các trang kế tiếp, rồi phân ngành kế tiếp theo thứ tự.
- Chống trùng bằng ID, dùng lại cùng DB và dữ liệu cũ; chỉ bổ sung ngành khi gặp lại công ty.
- Lưu từng công ty và trạng thái done trong cùng giao dịch. Không đợi một lô lớn mới lưu.
- Xuất đủ tên, địa chỉ, điện thoại, email, website và thông tin nguồn/ngành; thiếu trường vẫn đánh dấu cần kiểm tra.
- Thống kê, log công ty, timeout, dừng/tiếp tục, xử lý xác minh và robots vẫn hoạt động. Không tự giải CAPTCHA hoặc bỏ qua trang chặn.
- Không mở nhiều luồng tải trang. Khoảng nghỉ giữa các yêu cầu chính vẫn tối thiểu theo robots.txt; mặc định delay 5 giây. Nếu nguồn yêu cầu 9 giây, v2 dùng ít nhất 9 giây.

## Tăng tốc ở đâu

1. **Chế độ cân bằng mặc định:** chặn video/audio và các hostname quảng cáo/đo lường phổ biến được liệt kê trong mã. Vẫn tải ảnh, font, CSS và JS nội dung. Các đường dẫn/hostname xác minh được cho qua, và ngừng lọc tài nguyên trong lúc chờ xác minh. Một số website có thể phụ thuộc mã bên thứ ba: dùng chế độ full bên dưới nếu thấy dữ liệu/giao diện bất thường.
2. **Chỉ phân tích HTML công ty một lần:** dùng lại cây HTML đã có khi trích xuất 5 trường, tránh dựng lại toàn bộ BeautifulSoup.
3. **Không ghi HTML phụ mặc định:** giảm dung lượng và thao tác ghi đĩa, nhất là khi quét nhiều công ty. SQLite, log và CSV/Excel vẫn lưu bình thường. Bản HTML cũ trong data/html không bị xóa.
4. **SQLite WAL + synchronous FULL:** giảm cạnh tranh đọc/ghi với luồng thống kê nhưng giữ ghi nhận bền vững từng tác vụ; không dùng synchronous OFF/NORMAL để đổi độ an toàn lấy tốc độ. DB/khóa chống trùng có cùng định dạng với v1.
5. **Giảm quét lại bộ đếm:** dòng tổng kết được in sau mỗi 10 tác vụ; thống kê định kỳ mặc định 10 giây. Tên và dữ liệu từng công ty vẫn được in ngay sau commit.
6. File chay_v2.bat không thêm thời gian jitter 0–1 giây như file .bat v1, nhưng vẫn giữ khoảng nghỉ chuẩn 5 giây/robots. Có thể đặt --jitter 1 nếu muốn như cũ.

## Các lựa chọn

Bình thường chỉ cần `python crawler_v2.py select`.

Nếu muốn mọi tài nguyên tải giống v1:

```powershell
python crawler_v2.py select --v2-assets full
```

Nếu muốn lưu HTML mỗi trang và in dòng tổng kết sau mọi tác vụ như v1:

```powershell
python crawler_v2.py select --v2-assets full --save-html --progress-every 1
```

Chế độ nhẹ hơn, **chỉ bật sau khi đối chiếu dữ liệu thử**:

```powershell
python crawler_v2.py select --v2-assets lean
```

Lean còn chặn ảnh và font trên trang chi tiết công ty. Trang danh sách/lĩnh vực vẫn giữ ảnh/font để tránh thay đổi bố cục khi tìm liên kết. Không có cam kết mọi template đều tương thích; full là cách tắt lọc khi cần.

Các tùy chọn cũ như --category, --db, --out, --max-pages, --delay, --jitter, --stats-every, --verify-timeout, --page-timeout, --proxy-env vẫn dùng được. Giá trị bạn nhập được giữ nguyên, không tự hạ thấp delay. --progress-every N điều chỉnh tần suất dòng tổng kết; --stats-every N điều chỉnh thống kê theo giây.

## Bằng chứng kiểm thử và giới hạn tốc độ

- **61 kiểm thử Python**: 48 kiểm thử cũ và 13 kiểm thử v2 cho chính sách tài nguyên, tài nguyên xác minh, dữ liệu cũ/cùng scope, WAL/FULL, rollback, chống trùng, trường dữ liệu, cache và tùy chọn tốc độ.
- Chromium thật trên **trang mẫu cục bộ**, 3 trang, có script quảng cáo chậm 6 giây/trang; cả hai giữ khoảng nghỉ 5 giây giữa lần bắt đầu điều hướng:

| Bài đo | Thời gian 3 trang |
|---|---:|
| Browser cơ sở không lọc | 18,439 giây |
| V2 balanced | 10,083 giây |

Tỷ lệ trong bài đo này: 1,83 lần. Năm trường dữ liệu và cờ kiểm tra của cả hai bản khớp nhau; tài nguyên mẫu thuộc hostname xác minh vẫn được tải ở cả hai. Kết quả chi tiết ở benchmarks/result.json. Bài đo không bao gồm khởi động Chrome.

**Đây là bài đo tổng hợp, không phải tốc độ đã đo trên Trang Vàng thực tế.** Nếu trang thật ít quảng cáo hoặc đã tải dưới 5 giây, giới hạn robots sẽ chi phối và mức tăng có thể nhỏ. Với delay 5 giây, giới hạn lý thuyết là khoảng 12 lượt tải trang chính/phút, chưa tính trang danh sách, xác minh và thời gian tải. Không cam kết hệ số tăng tốc cố định hoặc không bao giờ bị chặn.

Chạy lại bài đo (không crawl nguồn thật):

```powershell
python -m playwright install chromium
python benchmarks/benchmark_v2.py --report benchmarks/local-result.json
```

Có thể dùng --executable trỏ đến Chromium/Chrome đã cài. Bài đo chỉ trả trang mẫu qua bộ chặn mạng của harness, không gửi yêu cầu thu thập tới Trang Vàng.
