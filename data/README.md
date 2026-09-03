# Test 2 Synthetic Dataset Manifest

This directory contains the synthetic data pack supplied for BEDA AI Internship Test 2 (`SRC-HISYAM-T2-0903R18-A` and `SRC-HISYAM-T2-0903R18-B`). All people, organisations, addresses, messages, and figures are fictional.

## Manifest Mapping

| Source Component | Local File | Description |
|---|---|---|
| **Staff Directory** | `staff.json` | 4 BEDA staff members (Matt Cooper, Ties Rahardjo, Zidane Mouldino, Ali Pratama) with ownership domains. |
| **CRM Seed Rows** | `crm_seeds.json` | 5 pre-existing CRM records (C001–C005) for entity resolution and duplicate detection. |
| **Inbound Emails** | `emails.json` | 12 synthetic inbound email items (E001–E012) capturing diverse business scenarios. |
| **Attachment 01** | `attachments/01_hume_energy_bill.txt` | Truganina Distribution Centre electricity bill (68,420 kWh, 172 kW peak, $18,940). |
| **Attachment 02** | `attachments/02_northbank_site_notes.txt` | Northbank College lighting site notes (~1,100 fittings, missing bill, missing fixture schedule). |
| **Attachment 03** | `attachments/03_greenfields_invoice_query.txt` | Greenfields Foods billing query (PO GF PO 8821: $47,300 vs Invoice 1847: $49,940, variance $2,640). |

## Inbound Email Inventory

| ID | Sender | Company / Org | Stated Subject | Referenced Attachments |
|---|---|---|---|---|
| **E001** | `amelia.grant@humelogistics.example` | Hume Logistics Pty Ltd | Solar and battery across our three Victorian sites | `01_hume_energy_bill.txt` |
| **E002** | `a.grant@humelogistics.example` | Hume Logistic | Website enquiry | *(None)* |
| **E003** | `rohan@greenfieldsfoods.example` | Greenfields Foods Pty Ltd | Invoice 1847 does not match PO | `03_greenfields_invoice_query.txt` |
| **E004** | `sales@megaleadlists.example` | Sales Mega Leads | Buy 50,000 Australian CEO leads today | *(None)* |
| **E005** | `melissa.tran@northbankcollege.example` | Northbank College | Government school lighting upgrade | `02_northbank_site_notes.txt` |
| **E006** | `engineering@solarray.example` | Solarray | Harmonics question on proposed battery inverter | *(None)* |
| **E007** | `priya.dev@examplemail.test` | Job Candidate | Application for marketing internship | `portfolio.pdf` *(missing/external reference)* |
| **E008** | `daniel@solarainstall.example` | Solara Installations | Crew availability for Ballarat install | *(None)* |
| **E009** | `facilities@harbourcoldstores.example` | Harbour Coldstores | Electricity cost reduction | *(None)* |
| **E010** | `sam@harbourcoldstores.example` | Harbour Coldstores | Re: enquiry from our website | *(None)* |
| **E011** | `alerts@beda.example` | BEDA System Alert | CRM sync failed overnight | *(None)* |
| **E012** | `info@smallcafe.example` | Small Cafe Info | Solar for cafe | *(None)* |
