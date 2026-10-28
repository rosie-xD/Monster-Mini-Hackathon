"""Additional standalone detectors: invented records only, never uploaded datasets."""
import csv
import importlib
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUGS = ('phantom','undead_student','doppelganger','werewolf','web_crawler','shape_shifter')
MODULES = {name: importlib.import_module(name) for name in SLUGS}


def stamp(week=10, minute=0):
    time=datetime(2023,10,2,12,tzinfo=timezone.utc)+timedelta(weeks=week-1,minutes=minute)
    return time.isoformat().replace('+00:00','Z')


class AdditionalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.calendar=ROOT/'examples/synthetic/calendar.csv'

    def tearDown(self):
        self.temp.cleanup()

    def write(self,name,headers,rows):
        path=self.path/name
        with path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)
        return path

    def activity(self,lms=(),video=()):
        # Real activity schemas, with row/person/login identities independent of event content.
        paths=[]
        for source,records in [('lms',lms),('video',video)]:
            records=list(records) or [dict(pid='SYNTH_CONTROL_'+source,time=stamp(),resource='control')]
            resource_col='LMS_ITEM_ID' if source=='lms' else 'VIDEO_ID'
            headers=['P_ID','DATE','TIMESTAMP','PIT_ID' if source=='lms' else 'PVT_ID',resource_col]
            headers += ['INTERACTION_COUNT','TOTAL_SECONDS_BEFORE_NEXT_INTERACTION','LOGIN_ID'] if source=='lms' else ['TOTAL_MINUTES_DELIVERED','VIEWING_TYPE']
            out=[]
            for i,r in enumerate(records):
                pid=r['pid'];time=r.get('time',stamp());resource=r.get('resource','R')
                row=[pid,r.get('date',time[:10]),time,r.get('row_id',f'ID{i}'),resource]
                row += [r.get('count','1'),'0',f'login-{pid}'] if source=='lms' else [r.get('duration','1'),'Interactive Desktop On Demand']
                out.append(row)
            paths.append(self.write(source+'.csv',headers,out))
        return paths

    def run_script(self,name,lms=None,video=None,extra=(),script=None,success=True):
        args=[sys.executable,str(script or ROOT/(name+'.py'))]
        if name!='shape_shifter':args+=['--lms',str(lms),'--video',str(video)]
        if name in ('werewolf','shape_shifter'):args+=['--calendar',str(self.calendar)]
        result=subprocess.run(args+list(map(str,extra)),cwd=self.path,capture_output=True,text=True)
        if not success:return result
        self.assertEqual(result.returncode,0,result.stderr)
        output=self.path/json.loads(result.stdout)['output']
        self.assertTrue((output/'run_summary.json').exists())
        self.assertEqual(list(output.glob('working-*')),[])
        return output

    def read(self,path):
        with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

    def pids(self,path):
        return {r['P_ID'] for r in self.read(path/'findings.csv')}

    def persons(self,entries,typo=False):
        return self.write('persons.csv',['P_ID','deregristration_date' if typo else 'deregistration_date'],entries)

    def test_phantom_exact_duplicates_and_different_surrogate_ids(self):
        lms,video=self.activity([
            dict(pid='duplicate',row_id='SAME'),dict(pid='duplicate',row_id='SAME'),
            dict(pid='different_ids',row_id='ONE'),dict(pid='different_ids',row_id='TWO'),
            dict(pid='different_time',row_id='THREE',time=stamp(minute=1)),
        ])
        out=self.run_script('phantom',lms,video)
        self.assertEqual(self.pids(out),{'duplicate'})
        self.assertEqual(self.read(out/'duplicate_groups.csv')[0]['copies'],'2')
        out=self.run_script('phantom',lms,video,extra=['--ignore-columns','PIT_ID','PVT_ID'])
        self.assertEqual(self.pids(out),{'duplicate','different_ids'})
        self.assertTrue(json.loads((out/'run_summary.json').read_text())['provisional'])

    def test_phantom_sources_and_fields_are_not_conflated(self):
        lms,video=self.activity([dict(pid='same',resource='R')],[dict(pid='same',resource='R')])
        self.assertEqual(self.pids(self.run_script('phantom',lms,video)),set())

    def test_undead_strict_date_boundary_and_dictionary_spelling(self):
        lms,video=self.activity([dict(pid='same_day',time=stamp()),dict(pid='after',time=stamp(minute=1440))],
                                [dict(pid='no_dereg',time=stamp()),dict(pid='after',time=stamp(minute=2880))])
        for typo in (False,True):
            with self.subTest(typo=typo):
                persons=self.persons([['same_day',stamp()[:10]],['after',stamp()[:10]],['no_dereg','null']],typo)
                out=self.run_script('undead_student',lms,video,extra=['--persons',persons])
                self.assertEqual(self.pids(out),{'after'})
                row=next(r for r in self.read(out/'student_evidence.csv') if r['P_ID']=='after')
                self.assertEqual(row['post_deregistration_rows'],'2')

    def test_undead_requires_complete_unique_person_context(self):
        lms,video=self.activity([dict(pid='unknown')],[dict(pid='known')])
        persons=self.persons([['known','null']])
        result=self.run_script('undead_student',lms,video,extra=['--persons',persons],success=False)
        self.assertEqual(result.returncode,2);self.assertIn('absent from person_dim',result.stderr)
        persons=self.persons([['known','null'],['known','null']])
        result=self.run_script('undead_student',lms,video,extra=['--persons',persons],success=False)
        self.assertEqual(result.returncode,2);self.assertIn('duplicate person',result.stderr)

    def test_doppelganger_exact_multisets_both_members_and_normalized_timestamps(self):
        lms=[];video=[]
        for pid in ('pair_A','pair_B','extra_copy','changed_duration'):
            lms.append(dict(pid=pid,resource='L1',time=stamp()))
            video.append(dict(pid=pid,resource='V1',time=stamp(minute=30),duration='2' if pid=='changed_duration' else '1'))
        # Different UTC offsets represent the same instant, not a changed event.
        lms[1]['time']=stamp().replace('12:00:00Z','13:00:00+01:00')
        lms.append(dict(pid='extra_copy',resource='L1',time=stamp()))
        lms,video=self.activity(lms,video)
        out=self.run_script('doppelganger',lms,video)
        self.assertEqual(self.pids(out),{'pair_A','pair_B'})
        group=self.read(out/'matching_groups.csv')
        self.assertEqual({r['P_ID'] for r in group},{'pair_A','pair_B'})
        self.assertTrue(all(r['group_members']=='2' for r in group))
        out=self.run_script('doppelganger',lms,video,extra=['--min-events',3])
        self.assertEqual(self.pids(out),set())

    def test_doppelganger_groups_more_than_two_without_pair_explosion(self):
        lms,video=self.activity([dict(pid=p) for p in ('A','B','C')])
        out=self.run_script('doppelganger',lms,video)
        self.assertEqual(self.pids(out),{'A','B','C'})
        self.assertEqual(len(self.read(out/'matching_groups.csv')),3)

    def test_web_crawler_200_201_unique_resources_and_repeated_accesses(self):
        records=[]
        for pid,n in [('exact_200',200),('over_200',201),('repeats',300)]:
            records.extend(dict(pid=pid,resource=str(i) if pid!='repeats' else 'same') for i in range(n))
        lms,video=self.activity(records)
        out=self.run_script('web_crawler',lms,video)
        self.assertEqual(self.pids(out),{'over_200'})
        counts={r['P_ID']:int(r['max_distinct_resources_12h']) for r in self.read(out/'student_evidence.csv')}
        self.assertEqual(counts['exact_200'],200);self.assertEqual(counts['repeats'],1)

    def test_web_crawler_inclusive_12h_boundary_and_combined_resource_namespace(self):
        records=[dict(pid='boundary',resource=str(i),time=stamp()) for i in range(200)]
        records += [dict(pid='too_far',resource=str(i),time=stamp()) for i in range(200)]
        video=[dict(pid='boundary',resource='0',time=stamp(minute=720)),
               dict(pid='too_far',resource='0',time=stamp(minute=720).replace('00Z','00.000001Z'))]
        lms,video=self.activity(records,video)
        out=self.run_script('web_crawler',lms,video)
        self.assertEqual(self.pids(out),{'boundary'})
        counts={r['P_ID']:int(r['max_distinct_resources_12h']) for r in self.read(out/'student_evidence.csv')}
        self.assertEqual(counts['boundary'],201);self.assertEqual(counts['too_far'],200)

    def test_web_crawler_removes_stale_references_without_losing_recent_copies(self):
        records=[dict(pid='rolling',resource='repeat',time=stamp())]
        records += [dict(pid='rolling',resource=str(i),time=stamp(minute=721)) for i in range(199)]
        records += [dict(pid='rolling',resource='repeat',time=stamp(minute=720)),
                    dict(pid='rolling',resource='final',time=stamp(minute=721))]
        lms,video=self.activity(list(reversed(records)))
        out=self.run_script('web_crawler',lms,video)
        self.assertEqual(self.pids(out),{'rolling'})

    def wolf_data(self):
        rows=[]
        for pid,weeks in [('both',(2,8,15,21)),('autumn_only',(2,8)),('adjacent',(2,3,15,16))]:
            for week in weeks:rows.extend(dict(pid=pid,time=stamp(week=week)) for _ in range(30))
        # Uniform activity is not a spike even if it is plentiful.
        for week in range(1,27):rows.extend(dict(pid='steady',time=stamp(week=week)) for _ in range(30))
        return self.activity(rows)

    def test_werewolf_both_terms_separation_and_provisional_outputs(self):
        lms,video=self.wolf_data()
        out=self.run_script('werewolf',lms,video)
        self.assertEqual(self.pids(out),{'both'})
        self.assertTrue(all(r['Status']=='PROVISIONAL' for r in self.read(out/'findings.csv')))
        report=json.loads((out/'run_summary.json').read_text())
        self.assertTrue(report['provisional'])
        self.assertEqual(report['context']['baseline_weeks_per_term'],{'Autumn':13,'Spring':13})
        self.assertTrue(all(r['status']=='PROVISIONAL' for r in self.read(out/'student_evidence.csv')))
        out=self.run_script('werewolf',lms,video,extra=['--min-spike-rows',31])
        self.assertEqual(self.pids(out),set())
        result=self.run_script('werewolf',lms,video,extra=['--spike-multiplier','nan'],success=False)
        self.assertEqual(result.returncode,2)

    def history(self):
        return self.write('history.csv',['P_ID','EFFECTIVE_DATE','PROGRAMME_ID'],[
            ['switch',stamp(week=20)[:10],'B'],['switch',stamp(week=2)[:10],'A'],
            ['same',stamp(week=2)[:10],'A'],['same',stamp(week=20)[:10],'A'],
            ['concurrent',stamp(week=2)[:10],'A'],['concurrent',stamp(week=2)[:10],'B'],
            ['concurrent',stamp(week=20)[:10],'C'],['same',stamp(week=20)[:10],'A']])

    def test_shape_shifter_dated_switches_and_same_day_ambiguity(self):
        history=self.history()
        out=self.run_script('shape_shifter',extra=['--programme-history',history])
        self.assertEqual(self.pids(out),{'switch'})
        changes=self.read(out/'programme_changes.csv')
        self.assertEqual([(r['from_programme'],r['to_programme']) for r in changes],[('A','B')])
        self.assertEqual(self.read(out/'exceptions.csv')[0]['P_ID'],'concurrent')
        report=json.loads((out/'run_summary.json').read_text())
        self.assertTrue(report['details']['requires_supplementary_programme_history'])

    def test_shape_shifter_does_not_use_module_or_department_as_programme(self):
        result=self.run_script('shape_shifter',success=False)
        self.assertEqual(result.returncode,2);self.assertIn('--programme-history',result.stderr)
        fake=self.write('module.csv',['P_ID','MODULE_INSTANCE_ID','DEPARTMENT_ID'],[['A','I123','D01']])
        result=self.run_script('shape_shifter',extra=['--programme-history',fake],success=False)
        self.assertEqual(result.returncode,2);self.assertIn('PROGRAMME_ID',result.stderr)

    def test_six_new_scripts_standalone_zip_parts_and_error_outputs(self):
        lms,video=self.activity([dict(pid='one')],[dict(pid='two')])
        persons=self.persons([['one','null'],['two','null']]);history=self.history()
        data=lms.read_bytes();parts=[self.path/'part_aa',self.path/'part_ab']
        parts[0].write_bytes(data[:27]);parts[1].write_bytes(data[27:])
        zipped=self.path/'video.zip'
        with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as z:z.write(video,'video.csv')
        for name in SLUGS:
            with self.subTest(script=name):
                # Copy only one script to prove it has no imports from sibling files.
                script=self.path/(name+'.py');shutil.copyfile(ROOT/script.name,script)
                extras=['--persons',persons] if name=='undead_student' else ['--programme-history',history] if name=='shape_shifter' else []
                out=self.run_script(name,lms,zipped,extra=extras,script=script)
                self.assertEqual(json.loads((out/'run_summary.json').read_text())['completed'],True)
                existing=self.run_script(name,lms,zipped,extra=extras+['--output',out],script=script,success=False)
                self.assertEqual(existing.returncode,2);self.assertIn('already exists',existing.stderr)
                if name!='shape_shifter':
                    command=[sys.executable,str(script),'--lms-parts',*map(str,parts),'--video',str(zipped)]
                    if name=='werewolf':command+=['--calendar',str(self.calendar)]
                    command+=list(map(str,extras))
                    result=subprocess.run(command,cwd=self.path,capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                else:
                    b=history.read_bytes();parts[0].write_bytes(b[:27]);parts[1].write_bytes(b[27:])
                    result=self.run_script(name,extra=['--history-parts',*parts],script=script)
                    self.assertEqual(self.pids(result),{'switch'})
                    parts[0].write_bytes(data[:27]);parts[1].write_bytes(data[27:])

    def test_new_detectors_reject_bad_timestamps_or_missing_resource_with_no_completion(self):
        lms,video=self.activity([dict(pid='one',time='broken',date=stamp()[:10])],[dict(pid='two')])
        persons=self.persons([['one','null'],['two','null']])
        for name in SLUGS[:-1]:
            extras=['--persons',persons] if name=='undead_student' else []
            output=self.path/(name+'-failed')
            result=self.run_script(name,lms,video,extra=extras+['--output',output],success=False)
            self.assertEqual(result.returncode,2);self.assertIn('line 2',result.stderr)
            self.assertFalse((output/'run_summary.json').exists())
            self.assertEqual(list(output.glob('working-*')),[])

    def test_web_window_matches_independent_brute_force(self):
        rng=random.Random(816)
        records=[];expected=[]
        for pid in ('random_A','random_B'):
            events=[]
            for _ in range(350):
                minute=rng.randrange(0,4000);resource=str(rng.randrange(80))
                records.append(dict(pid=pid,time=stamp(minute=minute),resource=resource))
                events.append((minute,resource))
            expected.append((pid,max(len({r for t,r in events if end-720<=t<=end}) for end,_ in events)))
        rng.shuffle(records)
        lms,video=self.activity(records)
        out=self.run_script('web_crawler',lms,video)
        actual={r['P_ID']:int(r['max_distinct_resources_12h']) for r in self.read(out/'student_evidence.csv')}
        for pid,peak in expected:self.assertEqual(actual[pid],peak)

    def test_doppel_hash_collision_is_not_treated_as_equality(self):
        module=MODULES['doppelganger'];output=self.path/'collision';output.mkdir()
        conn=sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE events (pid TEXT,payload TEXT)')
        conn.executemany('INSERT INTO events VALUES (?,?)',[('A','event-one'),('B','event-two'),('C','event-one')])
        fake=SimpleNamespace(update=lambda value:None,hexdigest=lambda:'forced-collision')
        try:
            with patch.object(module.hashlib,'sha256',return_value=fake):
                students,matches,details=module.detect(conn,SimpleNamespace(output=output,min_events=1),None,None)
            self.assertEqual((students,matches),(3,2))
            self.assertEqual(self.pids(output),{'A','C'})
        finally:
            conn.close()

    def test_large_input_crosses_multiple_batches_without_false_time_or_resource_counts(self):
        lms,video=self.activity([dict(pid='large',row_id='same')],[dict(pid='large',row_id='video')])
        lines=lms.read_text().splitlines()
        with lms.open('w') as f:
            f.write(lines[0]+'\n')
            for _ in range(100001):f.write(lines[1]+'\n')
        persons=self.persons([['large','null']])
        for name in ('phantom','doppelganger','web_crawler','undead_student','werewolf'):
            with self.subTest(script=name):
                extra=['--persons',persons] if name=='undead_student' else []
                out=self.run_script(name,lms,video,extra=extra)
                report=json.loads((out/'run_summary.json').read_text())
                self.assertEqual(report['rows']['lms']['included'],100001)
                self.assertEqual(report['rows']['video']['included'],1)
                self.assertEqual(self.pids(out),{'large'} if name=='phantom' else set())
        history=self.write('large_history.csv',['P_ID','EFFECTIVE_DATE','PROGRAMME_ID'],
                           (['large',stamp()[:10],'A'] for _ in range(100001)))
        out=self.run_script('shape_shifter',extra=['--programme-history',history])
        report=json.loads((out/'run_summary.json').read_text())
        self.assertEqual(report['rows']['programme_history']['included'],100001)
        self.assertEqual(self.pids(out),set())

    def test_missing_resource_ids_fail_and_shape_columns_are_configurable(self):
        lms,video=self.activity([dict(pid='one',resource='')],[dict(pid='two')])
        for name in ('web_crawler','doppelganger'):
            result=self.run_script(name,lms,video,success=False)
            self.assertEqual(result.returncode,2);self.assertIn('LMS_ITEM_ID',result.stderr)
        history=self.write('renamed.csv',['P_ID','WHEN','COURSE'],[['A',stamp(week=2)[:10],'ONE'],['A',stamp(week=20)[:10],'TWO']])
        out=self.run_script('shape_shifter',extra=['--programme-history',history,'--date-column','WHEN','--programme-column','COURSE'])
        self.assertEqual(self.pids(out),{'A'})

    def test_committed_examples_match_expected_for_all_nine_scripts(self):
        examples=ROOT/'examples/all_monsters'
        expected=json.loads((examples/'expected_findings.json').read_text())
        for name,pids in expected.items():
            with self.subTest(script=name):
                args=[sys.executable,str(ROOT/(name+'.py'))]
                if name!='shape_shifter':
                    args+=['--lms',str(examples/'lms.csv'),'--video',str(examples/'video.csv')]
                if name in ('ghost','werewolf','shape_shifter'):
                    args+=['--calendar',str(examples/'calendar.csv')]
                if name=='undead_student':args+=['--persons',str(examples/'persons.csv')]
                if name=='shape_shifter':args+=['--programme-history',str(examples/'programme_history.csv')]
                result=subprocess.run(args,cwd=self.path,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                output=self.path/json.loads(result.stdout)['output']
                self.assertEqual(self.pids(output),set(pids))


if __name__=='__main__':unittest.main()
