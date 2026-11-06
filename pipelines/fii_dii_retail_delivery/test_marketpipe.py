import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import marketpipe as m

DAY=date(2026,11,5)
HEADER='TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,TtlTradgVol,TtlTrfVal,ClsPric\n'
def price_bytes(day='2026-11-05'):
    return (HEADER+f'{day},{day},CM,NSE,STK,1,INE000000001,A,EQ,100,10000,100\n').encode()

def delivery_bytes(control=100):
    return (f'Security Wise Delivery Position\n10,MTO,05112026,{control},0000001\n'
            'Trade Date <05-NOV-2026>,Settlement Type <N>\n20,1,A,EQ,100,100,100.00\n').encode()

class ParserTests(unittest.TestCase):
    def test_wrong_internal_date_is_rejected(self):
        with self.assertRaises(ValueError):m.prices(price_bytes('2026-11-04'),DAY,'NSE')

    def test_html_is_not_accepted_as_csv(self):
        with self.assertRaises(ValueError):m.prices(b'<html>Access denied</html>',DAY,'NSE')

    def test_delivery_control_total(self):
        self.assertEqual(m.mto(delivery_bytes(),DAY)[('A','EQ')]['dq'],100)
        with self.assertRaises(ValueError):m.mto(delivery_bytes(99),DAY)

    def test_legacy_nse_schema_and_date(self):
        raw=b'SYMBOL,SERIES,TOTTRDQTY,TOTTRDVAL,CLOSE,TIMESTAMP,ISIN\nA,EQ,100,10000,100,07-NOV-2016,INE000000001\n'
        p=m.prices(raw,date(2016,11,7),'NSE')
        self.assertEqual(p[0]['v'],10000)

    def test_msei_rupee_file_not_scaled_udiff(self):
        raw=b'Date,Instrument,Symbol,Series,Currency Code,Volume (Quantity),Traded Value,Close\n11/5/2026,EQUITY,A,EQ,INR,100,10000,100\n'
        self.assertEqual(m.prices(raw,DAY,'MSEI')[0]['v'],10000)

    def test_bse_legacy_price_only_not_a_verified_zero(self):
        p=[{'key':'1','q':100,'v':10000,'close':100,'filename_date_only':True}]
        self.assertIsNone(m.aggregate('BSE',{'bse_prices':p}))

    def test_dated_msei_activity_confirms_zero_but_empty_statistics_does_not(self):
        raw=b'05/Nov/2026,,,,\nTraded Value (Rs.),0\nTraded Quantity,0\n'
        activity=m.parse('msei_activity',raw,DAY)
        r=m.aggregate('MSEI',{'msei_activity':activity})
        self.assertEqual(r['delivery_vwap_upper_inr'],0)
        self.assertEqual(r['traded_quantity'],0)
        self.assertIsNone(m.aggregate('MSEI',{}))
        with self.assertRaises(ValueError):m.parse('msei_activity',raw,date(2026,11,4))

    def test_msei_aggregate_fallback_does_not_claim_security_quantity(self):
        raw=b'05/Nov/2026\nTraded Value (Rs.),12345\nTraded Quantity,100\n'
        r=m.aggregate('MSEI',{'msei_activity':m.parse('msei_activity',raw,DAY)})
        self.assertEqual(r['delivery_vwap_upper_inr'],12345)
        self.assertIsNone(r['traded_quantity'])

    def test_nonpositive_close_is_unavailable(self):
        raw=price_bytes().replace(b',10000,100\n',b',10000,0\n')
        self.assertIsNone(m.prices(raw,DAY,'NSE')[0]['close'])

class CalculationTests(unittest.TestCase):
    def test_security_weighting_not_global_quantity_ratio(self):
        p=[{'key':('A','EQ'),'q':100,'v':10000,'close':100,'series':'EQ'},
           {'key':('B','EQ'),'q':100,'v':1000,'close':10,'series':'EQ'}]
        d={('A','EQ'):{'q':100,'dq':100},('B','EQ'):{'q':100,'dq':0}}
        r=m.aggregate('NSE',{'nse_prices':p,'nse_delivery':d})
        self.assertEqual(r['delivery_vwap_known_inr'],10000)
        self.assertNotEqual(r['delivery_vwap_known_inr'],11000*100/200)

    def test_missing_delivery_is_bounded_not_filled_as_zero(self):
        p=[{'key':('A','EQ'),'q':100,'v':10000,'close':100,'series':'EQ'}]
        r=m.aggregate('MSEI',{'msei_prices':p})
        self.assertEqual(r['missing_delivery_records'],1)
        self.assertEqual(r['delivery_vwap_upper_inr'],10000)
        self.assertEqual(r['delivery_quantity_coverage_by_turnover'],0)

    def test_true_zero_delivery_remains_reported(self):
        p=[{'key':('A','EQ'),'q':100,'v':10000,'close':100,'series':'EQ'}]
        r=m.aggregate('NSE',{'nse_prices':p,'nse_delivery':{('A','EQ'):{'q':100,'dq':0}}})
        self.assertEqual(r['missing_delivery_records'],0)
        self.assertEqual(r['delivery_quantity_coverage_by_turnover'],1)

    def test_tft_is_explicitly_derived(self):
        p=[{'key':('A','BE'),'q':100,'v':10000,'close':100,'series':'BE'}]
        r=m.aggregate('NSE',{'nse_prices':p})
        self.assertEqual(r['derived_delivery_records'],1)
        self.assertEqual(r['reported_delivery_records'],0)

    def test_missing_exchange_has_no_finite_upper_bound(self):
        ex={'NSE':{'delivery_vwap_known_inr':100,'delivery_vwap_upper_inr':100}}
        r=m.combine(str(DAY),ex,None)
        self.assertIsNone(r['x_vwap_upper_crore'])
        self.assertIsNone(r['rest_buy_lower_crore'])

    def test_net_does_not_validate_X(self):
        ins={'fii_buy':100,'fii_sell':50,'dii_buy':20,'dii_sell':30,'source':'test'}
        for value in (1000,2000):
            ex={k:{'delivery_vwap_known_inr':value*m.CRORE,'delivery_vwap_upper_inr':value*m.CRORE,
                   'delivery_close_known_inr':value*m.CRORE,'delivery_close_upper_inr':value*m.CRORE,
                   'turnover_inr':value*m.CRORE} for k in m.EXCHANGES}
            r=m.combine(str(DAY),ex,ins)
            self.assertEqual(r['rest_net_crore'],-40)
            self.assertEqual(r['rest_buy_lower_crore']-r['rest_sell_lower_crore'],-40)

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=m.Pipeline(self.tmp.name,delay=0,retries=0)
    def tearDown(self):
        self.p.close();self.tmp.cleanup()

    def test_cache_works_offline_without_network(self):
        self.p.save('nse_prices',DAY,price_bytes(),'test-source')
        self.p.offline=True
        with patch('marketpipe.network',side_effect=AssertionError('network must not run')):
            r=self.p.fetch_many(['nse_prices'],DAY)
        self.assertEqual(r['nse_prices'][0]['q'],100)

    def test_bad_refresh_preserves_good_snapshot(self):
        self.p.save('nse_prices',DAY,price_bytes(),'test-source')
        with patch('marketpipe.network',return_value=(price_bytes('2026-11-04'),200)):
            r=self.p.fetch_many(['nse_prices'],DAY,refresh=True)
        self.assertEqual(r['nse_prices'][0]['v'],10000)
        self.assertEqual(self.p.db.execute('SELECT status FROM attempts').fetchone()[0],'error')

    def test_revisions_are_preserved(self):
        self.p.put_institutions(DAY,100,50,20,30,'one');self.p.db.commit()
        self.p.put_institutions(DAY,101,50,20,30,'two');self.p.db.commit()
        self.assertEqual(self.p.db.execute('SELECT COUNT(*) FROM institution_revisions').fetchone()[0],1)

    def test_net_only_institution_values_are_rejected(self):
        with self.assertRaises(ValueError):self.p.put_institutions(DAY,None,None,20,30,'net-only')

if __name__=='__main__':unittest.main()
