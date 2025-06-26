import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import calendar

st.title("JJ Richards Invoice Extractor")

uploaded_file = st.file_uploader("Upload invoice PDF", type=["pdf"])

def process_pdf(file_bytes):
    all_data = []
    last_txn_index = None
    current_invoice = None
    current_customer = None
    current_issue_date = None
    current_transaction_total = None
    current_site = None
    current_description = None

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.splitlines()

            for line in lines:
                line = line.strip().replace("−", "-")  # Normalize minus sign

                if not line or any(skip in line for skip in [
                    "A.B.N.", "Continued from previous page", "Transaction details continued",
                    "Errors and Omissions", "Remittance Advice", "Page", "−F−", "INVOICE NUMBER"
                ]):
                    continue

                if m := re.search(r"Invoice No:\s+(\d+)", line):
                    current_invoice = m.group(1)
                    continue
                elif m := re.search(r"Customer No:\s+(\d+)", line):
                    current_customer = m.group(1)
                    continue
                elif m := re.search(r"Issue Date:\s+([\d/]+)", line):
                    current_issue_date = m.group(1)
                    continue
                elif m := re.search(r"Transactions for this period\s+\$([\d,]+\.\d{2})", line):
                    current_transaction_total = m.group(1).replace(",", "")
                    continue
                elif m := re.match(r"\((.*?)\)", line):
                    current_site = m.group(1).strip()
                    current_description = None
                    continue
                elif m := re.match(r"\*\*\*\s+(.*)", line):
                    current_description = m.group(1).strip()
                    continue

                # Strict SERVICE/BIN line with docket
                m = re.match(
                    r"(\d{2}/\d{2}/\d{2})\s+(\d+)\s+(BIN|SERVICE|BINS|SERVICES)\s+(\S+)?\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})",
                    line
                )
                if m:
                    booking_date, qty, desc_code, docket, price, gst, total = m.groups()
                    all_data.append({
                        "Invoice No": current_invoice,
                        "Customer No": current_customer,
                        "Issue Date": current_issue_date,
                        "Transactions for this period": current_transaction_total,
                        "Site": current_site,
                        "Description": current_description,
                        "Booking Date": booking_date,
                        "Qty": f"{qty} {desc_code}",
                        "Docket": docket,
                        "Price": float(price.replace(",", "")),
                        "GST": float(gst.replace(",", "")),
                        "Total": float(total.replace(",", "")),
                        "Additional Charges": 0.0,
                        "Tipping": None,
                        "Remarks": None
                    })
                    last_txn_index = len(all_data) - 1
                    continue

                # General fallback booking line
                m = re.match(
                    r"(\d{2}/\d{2}/\d{2})\s+(\d+)\s+([A-Z0-9/.-]+)\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})",
                    line
                )
                if m:
                    booking_date, qty, desc_code, price, gst, total = m.groups()
                    all_data.append({
                        "Invoice No": current_invoice,
                        "Customer No": current_customer,
                        "Issue Date": current_issue_date,
                        "Transactions for this period": current_transaction_total,
                        "Site": current_site,
                        "Description": current_description,
                        "Booking Date": booking_date,
                        "Qty": f"{qty} {desc_code}",
                        "Docket": None,
                        "Price": float(price.replace(",", "")),
                        "GST": float(gst.replace(",", "")),
                        "Total": float(total.replace(",", "")),
                        "Additional Charges": 0.0,
                        "Tipping": None,
                        "Remarks": None
                    })
                    last_txn_index = len(all_data) - 1
                    continue

                # Additional charges line
                if last_txn_index is not None and (m := re.match(
                    r"(DUMP FEE|OTHER CHARGE.*?)\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})\s+([-−]?\d[\d,]*\.\d{2})",
                    line, re.IGNORECASE)):
                    charge_desc, _, _, add_total = m.groups()
                    add_value = float(add_total.replace(",", ""))
                    all_data[last_txn_index]["Remarks"] = (
                        (all_data[last_txn_index]["Remarks"] or "") + f" | {charge_desc.strip()}"
                    ).strip(" |")
                    all_data[last_txn_index]["Additional Charges"] += add_value
                    all_data[last_txn_index]["Total"] += add_value
                    continue

                # Docket line
                if last_txn_index is not None and (m := re.match(r"(O/N:|#)\s*([A-Z0-9/-]+)", line)):
                    all_data[last_txn_index]["Docket"] = m.group(2)
                    continue

                # Tipping line
                if last_txn_index is not None and (m := re.match(r"([\d,.]+\s*(?:LITRES|T))", line, re.IGNORECASE)):
                    all_data[last_txn_index]["Tipping"] = m.group(1).replace(",", "")
                    continue

                # Remarks line - only specific ones
                if last_txn_index is not None:
                    allowed_remarks = {
                        "BIN WAS EMPTY", "CLOSED", "GATE LOCKED", "BLOCKED ACCESS", "BIN LOCKED",
                        "BIN NOT OUT", "BIN EMPTY", "TOO WET", "FLOODS", "ACCESS BLOCKED"
                    }
                    line_clean = line.upper().strip()
                    if any(line_clean.startswith(r) for r in allowed_remarks) or "EXCESS WEIGHT" in line_clean:
                        all_data[last_txn_index]["Remarks"] = (
                            (all_data[last_txn_index]["Remarks"] or "") + f" | {line.strip()}"
                        ).strip(" |")
                        continue

    df = pd.DataFrame(all_data)
    return df, current_issue_date

if uploaded_file:
    bytes_data = uploaded_file.read()
    st.info("Processing PDF...")
    df, issue_date = process_pdf(bytes_data)
    if df.empty:
        st.warning("No invoice data extracted.")
    else:
        # Fix numeric columns
        df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0)
        df["Additional Charges"] = pd.to_numeric(df["Additional Charges"], errors="coerce").fillna(0)
        df["Transactions for this period"] = pd.to_numeric(df["Transactions for this period"], errors="coerce")

        # Validation DataFrame
        validation_rows = []
        for invoice, group in df.groupby("Invoice No"):
            declared = group["Transactions for this period"].iloc[0]
            calculated = group["Total"].sum()
            match = abs(calculated - declared) < 0.01
            validation_rows.append({
                "Invoice No": invoice,
                "Declared Total": declared,
                "Calculated Total": round(calculated, 2),
                "Match": "✅ YES" if match else "❌ NO"
            })
        validation_df = pd.DataFrame(validation_rows)

        # Show results
        st.subheader("Extracted Invoice Data")
        st.dataframe(df)

        st.subheader("Invoice Validation")
        st.dataframe(validation_df)

        # Prepare Excel download
        output_buffer = io.BytesIO()
        with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Invoice Data", index=False)
            validation_df.to_excel(writer, sheet_name="Invoice Validation", index=False)
        output_buffer.seek(0)

        month_name = "UNKNOWN_MONTH"
        if issue_date:
            try:
                month_num = int(issue_date.split('/')[1])
                month_name = calendar.month_name[month_num]
            except Exception:
                pass

        excel_filename = f"JJ_RICHARDS_{month_name}.xlsx"

        st.download_button(
            label="Download Excel",
            data=output_buffer,
            file_name=excel_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
