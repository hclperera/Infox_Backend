"""Geometric regression tests with known cells, independent of Sinhala decoding."""
import unittest
import numpy as np
from services.grouping import GridConfig, group_dots_detailed


def detections(lines, angle=0., noise=0., seed=7, geometry=(15,15,40,60,10)):
    rng = np.random.default_rng(seed)
    theta = np.deg2rad(angle)
    rotation = np.array([[np.cos(theta), np.sin(theta)],[-np.sin(theta),np.cos(theta)]])
    output = []
    dx,dy,px,py,diameter = geometry
    for line, codes in enumerate(lines):
        for cell, code in enumerate(codes):
            for bit, present in enumerate(code):
                if present != '1':
                    continue
                point = np.array([100+cell*px+(bit//3)*dx,100+line*py+(bit%3)*dy]) @ rotation
                point += rng.normal(0,noise,2)
                output.append([2,point[0]/1000,point[1]/1000,diameter/1000,diameter/1000,.99])
    return output


def text_lines(result):
    lines, current = [], []
    for code in result['codes']:
        if code == '\n':
            lines.append(current);current=[]
        else:
            current.append(code)
    return lines


class GroupingTests(unittest.TestCase):
    def test_independently_bent_lines_recover_known_dot_sites(self):
        from services.line_refinement import refine_lines, line_sites
        ids=np.array([(cell,col,line,row) for line in range(5)
                      for cell in range(16) for col in range(2) for row in range(3)])
        ci,col,li,row=ids.T
        q=ci*(40/15)+col
        def coarse(q, rows, line):
            return np.column_stack([100+15*q,100+60*line+15*rows])
        points=np.column_stack([100+15*q,100+60*li+15*row]).astype(float)
        # Different curvature on each line cannot be represented by one
        # translation or page-wide quadratic. Identity is known in advance.
        shift=5.5*np.cos(li*np.pi)*((q-q.mean())/(np.ptp(q)/2))**2
        points[:,1]+=shift
        good=np.abs(shift)<=15*.28
        train=np.arange(len(points))%5!=0
        result=refine_lines(points,ci,col,li,row,good,train,
                            np.array([40/15,4.]),np.array([15.,15.]),.28,coarse)
        self.assertIsNotNone(result)
        self.assertTrue(np.all(result['good']))
        np.testing.assert_array_equal(np.column_stack([result[k] for k in ('ci','col','li','row')]),ids)
        for line in range(5):
            mask=li==line
            np.testing.assert_allclose(line_sites(q[mask],row[mask],result['models'][str(line)]),
                                       points[mask],atol=.05)

    def test_unfamiliar_spacing_and_image_scales(self):
        expected=[['111111','100000','000000','010100','101110','001111'],
                  ['111111','001010','101000','000000','000101','111111'],
                  ['111111']*6, ['111111']*6]
        for geometry in ((8,8,19.2,32,6),(20,18,56,81,12),
                         (12,16,39.6,83.2,9),(24,24,57.6,96,16)):
            with self.subTest(geometry=geometry):
                result=group_dots_detailed(detections(expected,noise=.1,geometry=geometry),1000,1000)
                self.assertEqual(text_lines(result),expected)

    def test_bits_spaces_rotation_and_jitter(self):
        expected = [['111111','100000','000000','010100','101110','001111'],
                    ['101000','001010','111111','000000','000101','110110'],
                    ['111111','111111','111111','111111','111111','111111']]
        for angle in (0.,4.,-4.):
            with self.subTest(angle=angle):
                result = group_dots_detailed(detections(expected,angle=angle,noise=.3),1000,1000)
                self.assertEqual(text_lines(result),expected)

    def test_full_isolated_line(self):
        expected=[['111111','100000','000000','001010','111111']]
        self.assertEqual(text_lines(group_dots_detailed(detections(expected),1000,1000)),expected)

    def test_curved_page_preserves_known_cells(self):
        rng=np.random.default_rng(42)
        expected=[[''.join(map(str,rng.integers(0,2,6))) for _ in range(16)] for _ in range(8)]
        for line in expected:
            line[0]=line[-1]='111111'
        rows=detections(expected)
        for dot in rows:
            x,y=dot[1]*1000,dot[2]*1000
            dot[1]=(x+.00004*(x-400)*(y-300))/1000
            dot[2]=(y+.00012*(x-400)**2)/1000
        result=group_dots_detailed(rows,1000,1000)
        self.assertEqual(result['grid']['fit_type'],'warped')
        self.assertEqual(text_lines(result),expected)

    def test_sparse_rows_cannot_silently_merge_lines(self):
        rows=detections([['010010']*6]*6)
        with self.assertRaises(ValueError):
            group_dots_detailed(rows,1000,1000)

    def test_calibration_recovers_sparse_rows(self):
        expected=[['010010']*6]*6
        cfg=GridConfig(angle_degrees=0,column_spacing=15,row_spacing=15,
                       cell_pitch=40,line_pitch=60,x_origin=100,y_origin=100)
        result=group_dots_detailed(detections(expected),1000,1000,config=cfg)
        self.assertEqual(text_lines(result),expected)
        self.assertEqual(result['grid']['accepted_fraction'],1.)

    def test_duplicate_back_dot_and_invalid_record(self):
        expected=[['111111']*5]*3
        rows=detections(expected)
        duplicate=rows[0].copy();duplicate[5]=.1
        back=rows[0].copy();back[0]=1
        rows.extend([duplicate,back,[2,float('nan'),.2,.01,.01]])
        result=group_dots_detailed(rows,1000,1000)
        self.assertEqual(text_lines(result),expected)
        self.assertIn('same-class duplicate',{r['reason'] for r in result['rejected']})
        self.assertIn('invalid detection',{r['reason'] for r in result['rejected']})

    def test_empty_input_and_invalid_configuration(self):
        self.assertEqual(group_dots_detailed([],1000,1000)['codes'],[])
        for config in (GridConfig(line_pitch_bounds=(4.,3.)),
                       GridConfig(min_accepted_fraction=0.),GridConfig(tolerance=.5)):
            with self.assertRaises(ValueError):
                group_dots_detailed([],1000,1000,config=config)


if __name__ == '__main__':
    unittest.main()
