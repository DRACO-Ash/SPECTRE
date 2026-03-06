#Simple script to demonstrate pulling data from the Unified Data Library (UDL)
#   and converting it into NumPy ndarray. This also demonstrates a useful
#   method for removing unwanted columns (fields) from the returned data.

import requests, base64, pandas as pd

#Pick one of the two following lines to set up your UDL login credentials.
#   The first option requires an open text username and password.
#   The second (preferred) option uses the value from the UDL Base64 token
#   utility (accessed via the Utility page of the UDL Storefront) to
#   create the encoded string.
basicAuth = "Basic " + base64.b64encode(("username:password").encode('utf-8')).decode("ascii")
# OR (comment one of these lines out)
basicAuth = "Basic aCharacterStringFromUDLutility=="

#Copy the URL from the UDL Dynamic Query Tool into the line below.
#   This sample query will return all element sets for the International
#   Space Station (satellite number 25544) generated 11-1-2018 or later.
url = "https://unifieddatalibrary.com/udl/elset?epoch=%3E2018-11-01T00:00:00.000000Z&satNo=25544"

#Make the actual REST call (ignore the InsecureRequestWarning).
result = requests.get(url, headers={'Authorization':basicAuth}, verify=False)

#JSON decodes easily in Python, into a list of dictionaries.
#   Uncomment the following 5 lines to pretty-print the JSON results.
#   This is useful for finding the exact field names for filtering out
#   unwanted columns.

#obs = result.json()
#for ob in obs:
#   for key, value in ob.items():
#     print(key, ":", value)
#   print("\n")

#There are more columns (fields) of data than we need, and rather than a list
#   of dictionaries, we generally want a NumPy ndarray to work with most
#   analytical and machine learning tools. We can use a Pandas DataFrame to do
#   the heavy lifting of deleting unwanted columns and converting to a NumPy
#   ndarray.
elsetsDataFrame = pd.DataFrame(result.json())
keepColumns = ['epoch','meanMotion','eccentricity','inclination','meanAnomaly']
elsetsArray = elsetsDataFrame[keepColumns].values

print(elsetsArray)

#Insert analytical application code here.