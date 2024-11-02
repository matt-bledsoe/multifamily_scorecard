import pandas as pd
import duckdb

# Data infile
data_file = "raw_data/FNMA_MF_Loan_Performance_Data__202403.csv"

# Read in pre-defined schema
schema = pd.read_csv("mflpd_schema.csv", index_col=0)
# Read in headers of data file to ensure order of columns
mflpd_cols = pd.read_csv(data_file, header=None, nrows=1).T
schema = schema.reindex(mflpd_cols[0])

# Create a dict that contains new column names DuckDB types, use that to create
# a relation of the loan performance data
db_column_types = pd.Series(schema["type"].values,
                            index=schema["name"]).to_dict()
mflpd = duckdb.sql(
    f"SELECT * FROM read_csv('{data_file}', columns={db_column_types})"
)

print(duckdb.sql("DESCRIBE SELECT * FROM mflpd"))
