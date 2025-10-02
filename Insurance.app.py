import streamlit as st
import pdfplumber
import pandas as pd
import io
from fuzzywuzzy import fuzz  # pip install fuzzywuzzy python-levenshtein for speed

# Streamlit app title
st.title("Insurance Estimate Breakdown & Contractor Delegator (Varied Formats)")

# Sidebar for user inputs
st.sidebar.header("Contractor Setup")
contractors = {}
num_contractors = st.sidebar.number_input("Number of Contractors", min_value=1, max_value=5, value=2)
for i in range(num_contractors):
    name = st.sidebar.text_input(f"Contractor {i+1} Name", value=f"Contractor {i+1}")
    percentage = st.sidebar.slider(f"{name} Percentage (%)", 0.0, 100.0, 85.0)
    contractors[name] = percentage / 100.0

st.sidebar.header("Category-Based Rules")
# Common categories inspired by CSI MasterFormat
categories = ["Roofing", "Electrical", "Plumbing", "Drywall/Painting", "Foundation/Concrete", "Other"]
rules = {}
num_rules = st.sidebar.number_input("Number of Rules", min_value=0, max_value=10, value=3)
for i in range(num_rules):
    category = st.sidebar.selectbox(f"Rule {i+1} Category", categories)
    assigned_to = st.sidebar.selectbox(f"Assign {category} To", list(contractors.keys()) + ["Unassigned"])
    rules[category] = assigned_to

# Keyword mappings for categorization (expand as needed)
category_keywords = {
    "Roofing": ["shingle", "ridge", "flashing", "felt", "ice water"],
    "Electrical": ["wiring", "outlet", "panel", "fixture"],
    "Plumbing": ["pipe", "vent", "fixture", "drain"],
    "Drywall/Painting": ["drywall", "paint", "texture", "ceiling"],
    "Foundation/Concrete": ["footing", "pile", "rebar", "concrete"],
    "Other": []  # Catch-all
}

# File upload
uploaded_file = st.file_uploader("Upload Insurance Estimate PDF (Xactimate, Symbility, etc.)", type="pdf")

if uploaded_file is not None:
    # Extract tables from PDF
    tables = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            if page_tables:
                for table in page_tables:
                    if len(table) > 1:  # Skip empty
                        df = pd.DataFrame(table[1:], columns=table[0])
                        # Clean columns
                        df.columns = df.columns.astype(str).str.strip().str.lower().str.replace(' ', '_').str.replace('.', '')
                        tables.append(df)
    
    if tables:
        # Concat all potential tables
        all_raw = pd.concat([df for df in tables if len(df) > 1], ignore_index=True)
        
        # Auto-map columns with fuzzy matching
        desc_col = None
        total_col = None
        qty_col = None
        unit_col = None
        
        for col in all_raw.columns:
            # Description: high match to 'description', 'desc', etc.
            if fuzz.ratio(col, 'description') > 70 or 'desc' in col:
                desc_col = col
            # Total/Price: match to 'total', 'price', 'rcv', etc.
            if fuzz.ratio(col, 'total') > 70 or 'price' in col or 'rcv' in col:
                total_col = col
            # Qty
            if fuzz.ratio(col, 'quantity') > 70 or 'qty' in col:
                qty_col = col
            # Unit
            if fuzz.ratio(col, 'unit') > 70:
                unit_col = col
        
        # Fallback: Let user map if auto-detect fails
        if not desc_col or not total_col:
            st.warning("Auto-detection partial—please map columns below.")
            col_options = {col: col for col in all_raw.columns}
            desc_col = st.selectbox("Select Description Column", options=list(col_options.keys()), index=0 if desc_col else None)
            total_col = st.selectbox("Select Total/Price Column", options=list(col_options.keys()), index=0 if total_col else None)
            if desc_col and total_col:
                st.rerun()  # Refresh on selection
        
        if desc_col and total_col:
            # Extract and clean
            all_tasks = all_raw[[desc_col, total_col]].dropna()
            all_tasks.columns = ['description', 'total']
            all_tasks['total'] = pd.to_numeric(all_tasks['total'].astype(str).str.replace(r'[\$,]', '', regex=True), errors='coerce')
            all_tasks = all_tasks.dropna(subset=['total'])
            
            # Add category via keywords
            all_tasks['category'] = 'Other'
            for idx, row in all_tasks.iterrows():
                desc_lower = str(row['description']).lower()
                for cat, kws in category_keywords.items():
                    if any(kw in desc_lower for kw in kws):
                        all_tasks.at[idx, 'category'] = cat
                        break
            
            st.subheader("Extracted & Standardized Tasks")
            if qty_col:
                all_tasks['qty'] = all_raw[qty_col]
                if unit_col:
                    all_tasks['unit'] = all_raw[unit_col]
                st.dataframe(all_tasks, use_container_width=True)
            else:
                st.dataframe(all_tasks, use_container_width=True)
            
            # Delegate by category rules
            all_tasks['assigned_to'] = 'Unassigned'
            for idx, row in all_tasks.iterrows():
                cat = row['category']
                if cat in rules:
                    all_tasks.at[idx, 'assigned_to'] = rules[cat]
            
            st.subheader("Delegated Tasks (by Category)")
            st.dataframe(all_tasks, use_container_width=True)
            
            # Calculate payments
            payments = {}
            for contractor, pct in contractors.items():
                assigned_total = all_tasks[all_tasks['assigned_to'] == contractor]['total'].sum()
                payment = assigned_total * pct
                payments[contractor] = payment
            
            st.subheader("Contractor Payments")
            payment_df = pd.DataFrame(list(payments.items()), columns=['Contractor', 'Payment Amount'])
            st.dataframe(payment_df, use_container_width=True)
            
            # Grand totals
            grand_total = all_tasks['total'].sum()
            st.metric("Total Estimate Value", f"${grand_total:,.2f}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Assigned Total", f"${all_tasks[all_tasks['assigned_to'] != 'Unassigned']['total'].sum():,.2f}")
            with col2:
                st.metric("Unassigned Total", f"${all_tasks[all_tasks['assigned_to'] == 'Unassigned']['total'].sum():,.2f}")
            with col3:
                st.metric("Categorized %", f"{(len(all_tasks[all_tasks['category'] != 'Other']) / len(all_tasks) * 100):.0f}%")
        else:
            st.error("Could not map columns—check PDF tables.")
    else:
        st.warning("No tables detected. Ensure PDF has line-item tables (try exporting from software as PDF).")
else:
    st.info("Upload a PDF to start. Pro tip: Test with Xact or Symb samples for varied formats.")
