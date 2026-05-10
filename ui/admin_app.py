"""Streamlit admin screen for ReserveLine Pro."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

# Allow `streamlit run ui/admin_app.py` from the project root.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.line_webhook import handle_user_message
from app.reservation_service import ReservationInput, ReservationService, STATUS_LABELS, WEEKDAY_KEYS
from app.reminder_service import ReminderService
from app.settings import get_settings

settings = get_settings()
service = ReservationService(settings.database_path)

st.set_page_config(page_title="LINE予約受付・予約管理システム", layout="wide")


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"], .stApp {
            font-size: 17px;
            color: #1f2937;
        }
        .block-container {
            max-width: 1180px;
            padding-top: 1.6rem;
            padding-left: 1.4rem;
            padding-right: 1.4rem;
        }
        h1 {
            font-size: clamp(2rem, 4vw, 2.8rem) !important;
            font-weight: 800 !important;
            color: #111827 !important;
            letter-spacing: 0 !important;
        }
        h2, h3 {
            color: #111827 !important;
            font-weight: 750 !important;
            letter-spacing: 0 !important;
        }
        h2 {
            font-size: 1.55rem !important;
        }
        h3 {
            font-size: 1.35rem !important;
        }
        p, li, label, .stMarkdown, [data-testid="stMarkdownContainer"] {
            color: #1f2937 !important;
            font-size: 1rem;
            line-height: 1.75;
        }
        .app-description {
            font-size: 1.08rem;
            font-weight: 700;
            color: #1f2937;
            line-height: 1.8;
            margin: 0.35rem 0 0.45rem;
        }
        .app-sub-description {
            font-size: 1.02rem;
            font-weight: 500;
            color: #374151;
            line-height: 1.8;
            margin: 0 0 0.9rem;
        }
        .notice-box {
            font-size: 1.02rem;
            font-weight: 700;
            color: #1e3a8a;
            background-color: #eaf4ff;
            border-left: 5px solid #2563eb;
            padding: 0.85rem 1.1rem;
            border-radius: 8px;
            line-height: 1.75;
            margin: 1rem 0 1.15rem;
        }
        .page-guide,
        .sidebar-help {
            font-size: 1rem;
            color: #374151;
            line-height: 1.75;
            margin-bottom: 0.65rem;
        }
        [data-testid="stCaptionContainer"] p {
            color: #4b5563 !important;
            font-size: 0.96rem !important;
            line-height: 1.7 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 1rem !important;
            color: #243040 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 2rem !important;
            color: #111827 !important;
        }
        section[data-testid="stSidebar"] {
            font-size: 1rem;
        }
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
            color: #1f2937 !important;
            font-size: 1rem !important;
            line-height: 1.7;
        }
        section[data-testid="stSidebar"] h3 {
            font-size: 1.18rem !important;
            color: #111827 !important;
        }
        div[role="radiogroup"] label {
            min-height: 2.35rem;
            align-items: center;
        }
        div[role="radiogroup"] label p,
        div[role="radiogroup"] label span {
            font-size: 1rem !important;
            color: #111827 !important;
        }
        .stButton button, .stDownloadButton button, .stFormSubmitButton button {
            min-height: 3rem;
            padding: 0.75rem 1.1rem;
            font-size: 1rem !important;
            font-weight: 700;
            border-radius: 8px;
        }
        .stButton button p,
        .stDownloadButton button p,
        .stFormSubmitButton button p {
            font-size: 1rem !important;
            font-weight: 700 !important;
            line-height: 1.3 !important;
        }
        [data-testid="stWidgetLabel"] p {
            color: #111827 !important;
            font-size: 1rem !important;
            font-weight: 650 !important;
            line-height: 1.55 !important;
        }
        .stTextInput input, .stNumberInput input, .stDateInput input,
        .stTimeInput input, .stSelectbox div[data-baseweb="select"] > div,
        .stTextArea textarea, textarea {
            min-height: 2.9rem;
            font-size: 1rem !important;
            color: #111827 !important;
        }
        .stSelectbox div[data-baseweb="select"] span,
        .stMultiSelect div[data-baseweb="select"] span,
        .stDateInput input,
        .stTimeInput input {
            font-size: 1rem !important;
            color: #111827 !important;
        }
        .stCheckbox label p,
        .stCheckbox label span {
            font-size: 1rem !important;
            color: #111827 !important;
        }
        div[data-testid="stForm"] {
            padding-top: 0.35rem;
        }
        div[data-testid="stForm"] > div {
            gap: 0.7rem;
        }
        [data-testid="stDataFrame"] {
            font-size: 1rem !important;
        }
        [data-testid="stDataFrame"] div,
        [data-testid="stDataFrame"] span,
        [data-testid="stDataFrame"] p,
        [role="gridcell"],
        [role="columnheader"] {
            font-size: 0.96rem !important;
            color: #111827 !important;
        }
        [data-testid="stTable"] table {
            font-size: 1rem !important;
        }
        div[data-testid="stAlert"] {
            font-size: 1rem !important;
            color: #1f2937 !important;
        }
        div[data-testid="stAlert"] p {
            font-size: 1rem !important;
            line-height: 1.7 !important;
        }
        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.8rem;
                padding-right: 0.8rem;
            }
            h1 {
                font-size: 1.85rem !important;
            }
            h2 {
                font-size: 1.35rem !important;
            }
            h3 {
                font-size: 1.2rem !important;
            }
            html, body, [class*="css"], .stApp,
            p, li, label, .stMarkdown, [data-testid="stMarkdownContainer"],
            .app-description,
            .app-sub-description,
            .notice-box,
            .page-guide,
            .sidebar-help {
                font-size: 1rem !important;
            }
            [data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
            }
            .stButton button, .stDownloadButton button, .stFormSubmitButton button {
                width: 100%;
                min-height: 3rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_global_style()


def require_login() -> None:
    if st.session_state.get("admin_logged_in"):
        return

    st.title("管理画面ログイン")
    if not settings.admin_password:
        st.warning("管理者パスワードが設定されていません。.env の ADMIN_PASSWORD を設定してください。")
        st.stop()

    with st.form("admin_login_form"):
        password = st.text_input("管理者パスワードを入力してください", type="password")
        submitted = st.form_submit_button("ログイン")

    if submitted:
        if password == settings.admin_password:
            st.session_state["admin_logged_in"] = True
            st.rerun()
        else:
            st.error("パスワードが正しくありません。")
    st.stop()


require_login()

st.title("LINE予約受付・予約管理システム")
st.markdown(
    """
    <div class="app-description">
      LINEから入った予約を管理できる、小規模店舗向けの予約管理システムです。
    </div>
    <div class="app-sub-description">
      お客様はLINEで予約・確認・キャンセルができ、店舗側はこの管理画面で予約状況を確認できます。
    </div>
    """,
    unsafe_allow_html=True,
)

if st.sidebar.button("ログアウト"):
    st.session_state["admin_logged_in"] = False
    st.rerun()

if settings.demo_mode:
    st.markdown(
        """
        <div class="notice-box">
          LINE公式アカウントとつなぐ前でも、予約受付や管理画面の動きを確認できます。
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.success("LINE公式アカウントと接続されています。チャネル設定とWebhook URLを確認してください。")


def yes_no(value: object) -> str:
    return "はい" if bool(value) else "いいえ"


def format_datetime_text(value: object) -> str:
    return str(value).replace("T", " ") if value else ""


def to_dataframe(rows: list[dict], include_reminder_time: bool = False) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "status" in df.columns:
        df["予約状態"] = df["status"].map(STATUS_LABELS).fillna(df["status"])
    if "reservation_datetime" in df.columns:
        df["予約日時"] = df["reservation_datetime"].str.replace("T", " ", regex=False)
    if "reminder_sent" in df.columns:
        df["予約前のお知らせ済み"] = df["reminder_sent"].map(lambda value: "送信済み" if bool(value) else "未送信")
    if include_reminder_time and "reservation_datetime" in df.columns:
        reminder_delta = timedelta(hours=settings.reminder_hours_before)
        df["お知らせ予定日時"] = pd.to_datetime(df["reservation_datetime"]).sub(reminder_delta).dt.strftime("%Y-%m-%d %H:%M")
    rename_map = {
        "id": "予約ID",
        "customer_name": "顧客名",
        "line_user_id": "LINEユーザーID",
        "menu": "メニュー",
        "notes": "備考",
        "created_at": "作成日時",
        "updated_at": "更新日時",
    }
    display_df = df.rename(columns=rename_map)
    preferred_columns = [
        "予約ID",
        "顧客名",
        "LINEユーザーID",
        "メニュー",
        "予約日時",
        "お知らせ予定日時",
        "予約状態",
        "備考",
        "予約前のお知らせ済み",
        "作成日時",
        "更新日時",
    ]
    return display_df[[column for column in preferred_columns if column in display_df.columns]]


def to_menu_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "active" in df.columns:
        df["受付中"] = df["active"].map(lambda value: "受付中" if bool(value) else "停止中")
    display_df = df.rename(
        columns={
            "id": "ID",
            "name": "メニュー名",
            "duration_minutes": "所要時間（分）",
            "price": "料金（円）",
            "display_order": "表示順",
            "created_at": "登録日時",
            "updated_at": "更新日時",
        }
    )
    preferred_columns = ["ID", "メニュー名", "所要時間（分）", "料金（円）", "受付中", "表示順", "登録日時", "更新日時"]
    return display_df[[column for column in preferred_columns if column in display_df.columns]]


def show_table(rows: list[dict], empty_message: str, include_reminder_time: bool = False) -> None:
    df = to_dataframe(rows, include_reminder_time=include_reminder_time)
    if df.empty:
        st.write(empty_message)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def refresh() -> None:
    st.rerun()


def next_business_date(start: date | None = None) -> date:
    current = start or date.today()
    for offset in range(1, 15):
        candidate = current + timedelta(days=offset)
        if WEEKDAY_KEYS[candidate.weekday()] in settings.business_days:
            return candidate
    return current + timedelta(days=1)


with st.sidebar:
    st.subheader("画面メニュー")
    page = st.radio(
        "表示する画面を選んでください",
        [
            "本日の予約",
            "今週の予約",
            "電話・店頭予約の登録",
            "キャンセルされた予約",
            "予約データをダウンロード",
            "予約メニューの設定",
            "予約前のお知らせ予定",
            "LINE予約の動作確認",
        ],
    )
    st.divider()
    st.subheader("確認用データ")
    st.markdown(
        '<div class="sidebar-help">画面確認用の予約データを作成します。</div>',
        unsafe_allow_html=True,
    )
    if st.button("確認用の予約データを作成"):
        try:
            result = service.create_demo_reservations()
            if result["created"]:
                st.success("確認用の予約データを作成しました。")
            else:
                st.info("既に同じ確認用の予約データがあります。重複登録はしていません。")
            if result["skipped"]:
                st.caption(f"既存の確認用予約：{len(result['skipped'])}件")
        except ValueError as exc:
            st.error(str(exc))


today_rows = service.list_reservations(start_date=date.today(), end_date=date.today())
week_rows = service.list_reservations(start_date=date.today(), end_date=date.today() + timedelta(days=6))
cancelled_rows = service.list_reservations(status="cancelled")
reminder_rows = service.get_due_reminders(datetime.now(), settings.reminder_hours_before)

col1, col2, col3, col4 = st.columns(4)
col1.metric("本日の予約", len(today_rows))
col2.metric("今週の予約", len(week_rows))
col3.metric("キャンセル", len(cancelled_rows))
col4.metric("予約前のお知らせ予定", len(reminder_rows))

st.markdown(
    """
    <div class="page-guide">
      左側の画面メニューから、確認したい内容を選んでください。スマホではメニューを開いて画面を切り替えられます。
    </div>
    <div class="page-guide">
      LINE公式アカウントとつなぐ前でも、予約受付や管理画面の動きを確認できます。
    </div>
    """,
    unsafe_allow_html=True,
)

if page == "本日の予約":
    st.subheader("本日の予約")
    show_table(today_rows, "本日の予約はありません。")

elif page == "今週の予約":
    st.subheader("今週の予約")
    show_table(week_rows, "今週の予約はありません。")

elif page == "電話・店頭予約の登録":
    st.subheader("電話・店頭予約の登録")
    st.write("電話や店頭で受けた予約を、店舗側で登録できます。")
    menus = [m["name"] for m in service.list_menus(active_only=True)]
    with st.form("create_reservation_form"):
        customer_name = st.text_input("顧客名", value="サンプル太郎")
        line_user_id = st.text_input("LINEユーザーID", value="sample-user-001")
        menu = st.selectbox("メニュー", menus, disabled=not menus)
        reservation_date = st.date_input("予約日", value=next_business_date())
        reservation_time = st.time_input("予約時間", value=datetime.strptime("10:00", "%H:%M").time())
        notes = st.text_area("備考", value="")
        submitted = st.form_submit_button("予約を登録する")
    if submitted:
        try:
            if not menus:
                raise ValueError("受付中のメニューがありません。先にメニューを登録してください。")
            reservation_dt = datetime.combine(reservation_date, reservation_time)
            reservation = service.create_reservation(
                ReservationInput(
                    customer_name=customer_name,
                    line_user_id=line_user_id,
                    menu=menu,
                    reservation_datetime=reservation_dt,
                    notes=notes,
                )
            )
            st.success(f"予約を登録しました。予約ID：{reservation['id']}")
        except ValueError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("予約状態を変更")
    all_rows = service.list_reservations()
    if not all_rows:
        st.write("変更できる予約がありません。")
    else:
        id_options = [int(row["id"]) for row in all_rows]
        selected_id = st.selectbox("予約ID", id_options)
        status = st.selectbox(
            "変更後の予約状態",
            options=list(STATUS_LABELS.keys()),
            format_func=lambda x: STATUS_LABELS[x],
        )
        if st.button("予約状態を変更する"):
            service.update_status(int(selected_id), status)
            st.success("予約状態を変更しました。")
            refresh()

elif page == "キャンセルされた予約":
    st.subheader("キャンセルされた予約")
    show_table(cancelled_rows, "キャンセルされた予約はありません。")

elif page == "予約データをダウンロード":
    st.subheader("予約データをダウンロード")
    st.write("Excelで開けるCSV形式で予約データを保存できます。")
    all_reservations = service.list_reservations()
    show_table(all_reservations, "予約データはまだありません。")
    csv_text = service.export_csv_japanese(all_reservations)
    st.download_button(
        "予約データをダウンロード",
        data=csv_text.encode("utf-8-sig"),
        file_name=f"reservations_{date.today():%Y%m%d}.csv",
        mime="text/csv",
    )

elif page == "予約メニューの設定":
    st.subheader("予約メニューの設定")
    st.write("お客様が選べる予約メニューを管理する画面です。メニュー名、所要時間、料金、表示順、受付中かどうかを設定できます。")
    menus_df = to_menu_dataframe(service.list_menus(active_only=False))
    if menus_df.empty:
        st.write("メニューがありません。")
    else:
        st.dataframe(menus_df, use_container_width=True, hide_index=True)

    with st.form("menu_form"):
        st.write("メニューを追加・更新します。同じメニュー名で保存すると、既存の内容を更新します。")
        name = st.text_input("メニュー名", value="30分相談")
        duration = st.number_input("所要時間（分）", min_value=5, max_value=480, value=30, step=5)
        price = st.number_input("料金（円）", min_value=0, max_value=1000000, value=0, step=500)
        display_order = st.number_input("表示順", min_value=0, max_value=999, value=1, step=1)
        active = st.checkbox("受付中にする", value=True)
        menu_submitted = st.form_submit_button("メニューを保存する")
    if menu_submitted:
        try:
            service.upsert_menu(name, int(duration), int(price), bool(active), int(display_order))
            st.success("メニューを保存しました。")
            refresh()
        except ValueError as exc:
            st.error(str(exc))

elif page == "予約前のお知らせ予定":
    st.subheader("予約前のお知らせ予定")
    st.write("予約の前にお客様へ送るお知らせの予定を確認できます。誰に、いつ、お知らせを送る予定かを一覧で確認するための画面です。")
    st.caption(f"現在から{settings.reminder_hours_before}時間以内にお知らせ対象となる予約を表示します。")
    show_table(reminder_rows, "現時点でお知らせ予定の予約はありません。", include_reminder_time=True)
    if st.button("お知らせ処理を確認する"):
        sent = ReminderService(service).send_due_reminders()
        st.success(f"{len(sent)}件の予約前のお知らせを処理しました。")

elif page == "LINE予約の動作確認":
    st.subheader("LINE予約の動作確認")
    st.write("実際の利用時は、お客様がLINEのトーク画面から予約します。この画面では、LINE公式アカウントとつなぐ前でも、予約受付の動きを確認できます。")
    active_menus = service.list_menus(active_only=True)
    sample_messages = ["予約", "確認", "キャンセル"]
    if active_menus:
        sample_messages.insert(
            1,
            f"予約 {active_menus[0]['name']} {next_business_date().isoformat()} 10:00",
        )
    message = st.selectbox("送信するメッセージ", sample_messages)
    custom_message = st.text_input("任意のメッセージ", value="")
    if st.button("LINEでの返信内容を確認する"):
        text = custom_message.strip() or message
        result = handle_user_message("sample-user-001", text, "サンプル太郎", service)
        st.code(result["reply_text"], language="text")
