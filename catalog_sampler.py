#!/user/bin/env python
from __future__ import print_function, division
from astropy.io import fits
import numpy as np
from astropy.io import ascii
from os.path import join, isdir, basename, normpath
from os import listdir, mkdir
import os
import argparse
import csv
from astropy import cosmology
from astropy.cosmology import Planck13
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys
import scipy.integrate as scint
import scipy.stats as stat
from scipy.stats import chi2
try:
	import healpy as hp
except ImportError:
	print('healpy import error')
import gc
import astropy.stats as astat

class RealCatalogue:

	def __init__(self, path):
		"""""
		read-in catalogue

		"""""
		self.path = path
		hdulist = fits.open(path)
		self.data = hdulist[1].data
		self.columns = hdulist[1].columns.names
		# ascii (.asc) file IDs
		self.labels = ['highZ_Red', 'highZ_Blue', 'lowZ_Red', 'lowZ_Blue', 'highZ', 'lowZ']
		# bodies of wcorr output file IDs
		self.wcorrLabels = ['highZ_vs_highZ_Red', 'highZ_vs_highZ_Blue', 'lowZ_vs_lowZ_Red', 'lowZ_vs_lowZ_Blue']

	def cut_data(self, pgm_, z_, colour_, *bitmask_): 
		"""""
		cut catalogue according to bitmasks, 
		PGM, & into subsamples

		"""""
		assert 'RA_1' in self.columns, "'RA_1' not in columns, see column headers: "+ str(self.columns)
		assert 'DEC_1' in self.columns, "'DEC_1' not in columns, see column headers: "+ str(self.columns)
		assert 'pgm' in self.columns, "'pgm' not in columns, see column headers: "+ str(self.columns)
		assert 'Z_1_1' in self.columns, "'Z_1_1' not in columns, see column headers: "+ str(self.columns)
		assert 'absmag_g_1' in self.columns, "'absmag_g_1' not in columns, see column headers: "+ str(self.columns)
		assert 'absmag_i_1' in self.columns, "'absmag_i_1' not in columns, see column headers: "+ str(self.columns)
		assert 'col3' in self.columns, "'col3' not in columns, see column headers: "+ str(self.columns)

		self.zstr = '%.f'%z_
		self.cstr = '%.f'%colour_

		# Remove duplicates in RA/DEC:
		# coordStrings = ['RA_1', 'DEC_1']
		# for i, col in enumerate(coordStrings):
		#   coords = self.data[col]
		#   uniqCoords = np.unique(coords, return_inverse=True, return_counts=True)
		#   inverse = uniqCoords[1]
		#   count = uniqCoords[2]
		#   orderedCount = count[inverse]
		#   duplicateCut = orderedCount == 1
		#   self.data = self.data[duplicateCut]
		#   print('Removed %s duplicates in %s' % ((len(duplicateCut)-len(self.data)), col[:-2]))

		pgm = self.data['pgm']
		pgm_cut = np.array((pgm > pgm_))
		zeroPgm_cut = np.array((pgm != 0))
		print('pgm cut: \t', np.unique(pgm_cut))

		self.pre_count = len(self.data)
		z = self.data['z_1_1']
		self.pre_z = z
		colour = self.data['absmag_g_1'] - self.data['absmag_i_1']
		total_bitmasks = self.data['col3']

		# define colour, redshift & bitmask cuts
		if colour_ != None:
			red_cut = np.array((colour > colour_)) # larger (B-V) <-> 'redder' colour
			blue_cut = ~red_cut
		else:
			red_cut = np.array([True]*len(self.data))
			blue_cut = red_cut
			print('Red catalog == Blue catalog')
		print('c cut: \t', colour_, np.unique(red_cut))
		if z_ != None:
			z_cut = np.array((z > z_)) # HIGH-Z
			z_cut_r = ~z_cut # LOW-Z
		else:
			z_cut = np.array([True]*len(self.data))
			z_cut_r = z_cut
			print('highZ catalog == lowZ catalog')
		print('z cut: \t', z_, np.unique(z_cut))

		bitmask_cut = [True]*len(total_bitmasks)
		if bitmask_[0] != None:
			bitmask_ = bitmask_[0]

			# bitmask_cut = []
			# for bit_test in total_bitmasks:
			#   for mask_ in bitmask_:
			#       if (mask_ & bit_test == mask_):
			#           bitmask_cut.append(False)
			#           break
			#       if mask_ == bitmask_[-1]:
			#           bitmask_cut.append(True)

			for i in np.arange(0,len(bitmask_)):
				# construct bitmask cut
				bitmask_cut &= np.where(bitmask_[i] & total_bitmasks == bitmask_[i], False, True)

			assert len(bitmask_cut) == len(total_bitmasks), "bitmask testing broken"
			bitmask_cut = np.array(bitmask_cut)
			print('bitmask cut: \t', np.unique(bitmask_cut))

		# apply cuts
		self.highz_R = self.data[(z_cut&red_cut&bitmask_cut)]
		self.highz_B = self.data[(z_cut&blue_cut&bitmask_cut)]
		self.lowz_R = self.data[(z_cut_r&red_cut&bitmask_cut)]
		self.lowz_B = self.data[(z_cut_r&blue_cut&bitmask_cut)]
		self.highz = self.data[z_cut]
		self.lowz = self.data[z_cut_r]

		self.samplecounts = []

		# save cuts for later use
		self.zcut = z_cut
		self.zcut_r = z_cut_r
		self.redcut = red_cut
		self.bluecut = blue_cut
		self.bitmaskcut = bitmask_cut
		self.pgmcut = pgm_cut

		return None

	def cut_columns(self, subsample, h): 
		"""""
		take subsample data 
		& isolate columns for wcorr

		"""""
		assert 'RA_1' in self.columns, "'RA_1' not in columns, see column headers: "+ str(self.columns)
		assert 'DEC_1' in self.columns, "'DEC_1' not in columns, see column headers: "+ str(self.columns)
		assert 'Z_1_1' in self.columns, "'Z_1_1' not in columns, see column headers: "+ str(self.columns)
		assert 'e1c' in self.columns, "'e1c' not in columns, see column headers: "+ str(self.columns)
		assert 'e2c' in self.columns, "'e2c' not in columns, see column headers: "+ str(self.columns)

		table = subsample
		RA = np.deg2rad(table['RA_1'])
		DEC = np.deg2rad(table['DEC_1'])
		Z = table['Z_1_1']
		pgm = table['pgm']
		e1 = table['e1c']/pgm
		e2 = table['e2c']/pgm
		e2 *= -1 # for RA increasing leftward, c.f. x-axis increasing rightward
		e_weight = np.where(pgm<0.1,0,pgm)
		e1,e2,e_weight = map(lambda x: np.nan_to_num(x), [e1,e2,e_weight])

		# random re-shuffle test - density-shape corr should now ~ 0
		# e12 = list(zip(e1,e2))
		# np.random.shuffle(e12)
		# e12 = np.array(e12)
		# e1 = e12[:,0]
		# e2 = e12[:,1]
		#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   

		comov = Planck13.comoving_distance(Z)
		comov *= h
		new_table = np.column_stack((RA, DEC, comov, e1, e2, e_weight))
		# new_table1 = new_table[enans]

		self.samplecounts.append(len(new_table))

		return new_table

	def save_tables(self, new_table, outfile_root_, label, z_cut, c_cut, notes):
		"""""
		save subsample tables to ascii

		"""""
		if notes != None:
			outfile_root_ += '_%s'%notes
		if (z_cut != None) & (c_cut != None):
			outfile_root = outfile_root_ + "_z" + str(z_cut) + "_c" + str(c_cut)
		elif z_cut != None:
			outfile_root = outfile_root_ + "_z" + str(z_cut)
		else:
			outfile_root = outfile_root_

		self.new_root = outfile_root
		zcCuts = [z_cut, c_cut]

		if not isdir(outfile_root):
			mkdir(outfile_root)

		np.savetxt(join(outfile_root, 'ZC_cuts'), zcCuts, delimiter=',', fmt="%f")

		ascii.write(new_table, join(outfile_root, label + ".asc"), names=['#RA/rad', '#DEC/rad', '#comov_dist/Mpc/h', '#e1', '#e2', '#e_weight'])

		sample_no = "%s # objects:\t%s"%(label,len(new_table))
		return sample_no

	def make_combos(self):
		# construct sets of filenames, counts, & IDs for wcorr-calls
		self.wcorr_combos = [
		[self.labels[4]+'.asc', self.samplecounts[4], self.labels[0]+'.asc', self.samplecounts[0], catalog.wcorrLabels[0]],
		[self.labels[4]+'.asc', self.samplecounts[4], self.labels[1]+'.asc', self.samplecounts[1], catalog.wcorrLabels[1]],
		[self.labels[5]+'.asc', self.samplecounts[5], self.labels[2]+'.asc', self.samplecounts[2], catalog.wcorrLabels[2]],
		[self.labels[5]+'.asc', self.samplecounts[5], self.labels[3]+'.asc', self.samplecounts[3], catalog.wcorrLabels[3]]
		]
		self.samplecounts = self.samplecounts[:6]
		[print('# objects %s: \t'%self.labels[i], v) for i, v in enumerate(self.samplecounts)]
		print('total shapes: \t%s'%np.sum(self.samplecounts[:4]))
		print('total density: \t%s'%np.sum(self.samplecounts[4:]))

	def prep_wcorr(self, files_path, wcorr_combos, rp_bins, rp_lims, los_bins, los_lim, nproc, large_pi, out_sh):
		shell_script = [
		'#!/bin/tcsh',
		'#PBS -q compute',
		'#PBS -N %s'%out_sh,
		'#PBS -l nodes=1',
		'#PBS -l walltime=120:00:00',
		'#PBS -l mem=50gb',
		'#PBS -o %s'%join(files_path,out_sh+'.out'),
		'#PBS -e %s'%join(files_path,out_sh+'.err'),
		'',
		'module load dev_tools/nov2014/python-anaconda',
		'',
		'cd $PBS_O_WORKDIR',
		'',
		'setenv LD_LIBRARY_PATH ${LD_LIBRARY_PATH}:/share/splinter/hj/PhD/CosmoFisherForecast/bjutils/lib/',
		'',
		'date']

		for combo in wcorr_combos: 
			# write 4x wcorr-calls to .sh script, & another 4x if largePi
			shell_script.append('')
			outfile = combo[4]
			shell_script.append('/share/splinter/hj/PhD/CosmoFisherForecast/obstools/wcorr %s %s %s %s %s %s %s %s %s %s %s %s 0 0' %   (files_path, combo[0], combo[1], combo[2], combo[3], rp_bins, rp_lims[0], rp_lims[1], los_bins, los_lim, outfile, nproc)
			)
			shell_script.append('')
			if large_pi:
				outfile += '_largePi'
				shell_script.append('')
				shell_script.append('/share/splinter/hj/PhD/CosmoFisherForecast/obstools/wcorr %s %s %s %s %s %s %s %s %s %s %s %s %s 0' %  (files_path, combo[0], combo[1], combo[2], combo[3], rp_bins, rp_lims[0], rp_lims[1], los_bins, los_lim, outfile, nproc, large_pi)
				)
			shell_script.append('')

			shell_script.append('date')

		File = join(files_path, '%s.sh'%out_sh)
		Write = open(File, 'w')
		Text = '\n'.join(shell_script)
		Write.write(str(Text))
		Write.close()

		wcorr_spec = [] # record parameters used in wcorr
		wcorr_spec.append('Comoving transverse separation r_p: %s - %s Mpc/h in %s log-spaced bins'%(rp_lims[0], rp_lims[1], rp_bins))
		wcorr_spec.append('Comoving line-of-sight separation \Pi: %s - %s Mpc/h in %s bins'%(los_lim*(-1), los_lim, los_bins))
		wcorr_spec.append('No. processors: %s'%nproc)
		wcorr_spec.append('Large-Pi systematics testing: %s'%large_pi)

		File = join(files_path, 'wcorr_spec')
		Write = open(File, 'w')
		Text = '\n'.join(wcorr_spec)
		Write.write(str(Text))
		Write.close()

	def plot_wcorr(self, files_path, wcorrIDs, BT, largePi):
		wcorrOutputs = []
		rand_wcorrOutputs = []
		for item in wcorrIDs:
			# construct filenames.dat
			wcorrOutputs.append('%s'%join(files_path, ('wcorr_' + item + '.dat')))
			rand_wcorrOutputs.append('%s'%join(files_path, ('wcorr_rand_' + item + '.dat')))
		realData = []
		randData = []
		wgplus = []
		wgcross = []
		wgerr = []
		Pproperrs = []
		Xproperrs = []
		rand_wgplus = []
		rand_wgcross = []
		rand_wgerr = []
		easyPlotDir = join(files_path, 'to_plot')
		if not isdir(easyPlotDir):
			mkdir(easyPlotDir)
		for i, path in enumerate(wcorrOutputs):
			realData.append(np.loadtxt(path))
			randData.append(np.loadtxt(rand_wcorrOutputs[i]))
			realData[i][:,3] -= randData[i][:,3]
			realData[i][:,4] -= randData[i][:,4] # subtracting randoms from +/x
			realErr = realData[i][:,6]
			randErr = randData[i][:,6]
			if BT:
				BTerrs = np.loadtxt(join(files_path,'BTerrs_%s'%self.labels[i]))
				if largePi:
					BTerrs = np.loadtxt(join(files_path,'BTerrs_%s_largePi'%self.labels[i]))
				Perr = BTerrs[:,0]
				Xerr = BTerrs[:,1]
				Pproperr = np.sqrt((Perr**2) + (randErr**2))
				Xproperr = np.sqrt((Xerr**2) + (randErr**2)) # propagate errors
				Pproperrs.append(Pproperr)
				Xproperrs.append(Xproperr)
			propgErrs = np.sqrt((realErr**2) + (randErr**2)) # propagate errors
			wgplus.append(realData[i][:,3])
			wgcross.append(realData[i][:,4])
			wgerr.append(propgErrs)
			rand_wgplus.append(randData[i][:,3])
			rand_wgcross.append(randData[i][:,4])
			rand_wgerr.append(randData[i][:,6])
			# save reduced data to csv for easy plotting
			if BT:
				reducedData = np.column_stack((realData[0][:,0], realData[i][:,3], Pproperr, realData[i][:,4], Xproperr, propgErrs)) # = [r_p, wgplus, Perr, wgcross, Xerr, analyticErrs]
				ascii.write(reducedData, join(easyPlotDir, basename(normpath(path))[6:-4]), delimiter='\t', names=['r_p', 'wg+', '+err', 'wgx', 'xerr', 'analyticerrs'])#, formats={'r_p':np.float32, 'wg+':np.float32,'+err':np.float32, 'wgx':np.float32, 'xerr':np.float32})
			else:
				reducedData = zip(realData[0][:,0], realData[i][:,3], realData[i][:,4], propgErrs) # = [r_p, wgplus, wgcross, wgerr]
				ascii.write(reducedData, join(easyPlotDir, basename(normpath(path))[6:-4]), delimiter='\t', names=['r_p', 'wgplus', 'wgcross', 'wgerr'], formats={'r_p':np.float32, 'wgplus':np.float32, 'wgcross':np.float32, 'wgerr':np.float32})

		r_p = realData[0][:,0]
		x = np.linspace(0, r_p.max()*1.8)
		if BT:
			data = [wgplus,wgcross,Pproperrs,Xproperrs]
			f, axarr = plt.subplots(2, 2, sharex=True, sharey=True, figsize=(15,10))
			f.subplots_adjust(hspace=0, wspace=0)
			axarr[0,0].errorbar(r_p,data[0][0],yerr=data[2][0],elinewidth=2, color='r', capsize=1,label='w(g+)',fmt='o')
			axarr[0,0].errorbar(r_p,data[1][0],yerr=data[3][0],elinewidth=2, color='g', capsize=1,label='w(gx)',alpha=0.5,fmt='^')
			axarr[0,1].errorbar(r_p,data[0][1],yerr=data[2][1],elinewidth=2, color='b', capsize=1,label='w(g+)',fmt='o')
			axarr[0,1].errorbar(r_p,data[1][1],yerr=data[3][1],elinewidth=2, color='g', capsize=1,label='w(gx)',alpha=0.5,fmt='^')
			axarr[1,0].errorbar(r_p,data[0][2],yerr=data[2][2],elinewidth=2, color='r', capsize=1,label='w(g+)',fmt='o')
			axarr[1,0].errorbar(r_p,data[1][2],yerr=data[3][2],elinewidth=2, color='g', capsize=1,label='w(gx)',alpha=0.5,fmt='^')
			axarr[1,1].errorbar(r_p,data[0][3],yerr=data[2][3],elinewidth=2, color='b', capsize=1,label='w(g+)',fmt='o')
			axarr[1,1].errorbar(r_p,data[1][3],yerr=data[3][3],elinewidth=2, color='g', capsize=1,label='w(gx)',alpha=0.5,fmt='^')
			arr_ind = [(0,0), (0,1), (1,0), (1,1)]
			for i, ind in enumerate(arr_ind):
				a = axarr[ind]
				a.set_xscale('log')
				a.set_xlim(0.25,70)
				a.set_ylim(-0.5,0.4)
				a.plot(x, [0]*len(x), lw=2, ls='--', color='c')
				# a.set_xlabel('Comoving transverse separation (Mpc/h)')
				# a.set_ylabel('Correlations')
				a.set_title('%s'%wcorrIDs[i], fontsize=12)
				a.legend(loc='upper right')
				a.grid()
			plt.setp([a.get_xticklabels() for a in axarr[0, :]], visible=False)
			plt.setp([a.get_yticklabels() for a in axarr[:, 1]], visible=False)
			# plt.setp([a.get_xlabels() for a in axarr[:, 1]], visible=False)
			axarr[1,0].set_xlabel('Comoving transverse separation (Mpc/h)')
			axarr[1,0].set_ylabel('Correlations')
			ZC = np.loadtxt(join(files_path, 'ZC_cuts'), delimiter=',')
			axarr[1,1].set_xlabel('Cuts: z%s, c%s'%(ZC[0],ZC[1]))
			if largePi:
				axarr[1,1].set_xlabel('largePi test, Cuts: z%s, c%s'%(ZC[0],ZC[1]))

			plotsDir = join(files_path, 'Plots')
			if not isdir(plotsDir):
				mkdir(plotsDir)

			if 'largePi' in wcorrOutputs[0]:
				outimg = join(plotsDir, 'wcorr_z%s_c%s_largePi.pdf'%(ZC[0],ZC[1]))
			else:
				outimg = join(plotsDir, 'wcorr_z%s_c%s.pdf'%(ZC[0],ZC[1]))
			f.savefig(outimg)
			try:
				plt.show()
			except RuntimeError:
				print("can't show plot :(")
		else:
			dataPoints = [[wgplus,wgcross,wgerr],[rand_wgplus,rand_wgcross,rand_wgerr]]
			prefix = ['','rand_']
			for j, set_ in enumerate(dataPoints): 
				# plot/save random-subtracted-reals, AND randoms
				f, axarr = plt.subplots(2, 2, sharex=True, sharey=True, figsize=(15,10))
				f.subplots_adjust(hspace=0, wspace=0)
				axarr[0,0].errorbar(r_p, set_[0][0], yerr=set_[2][0],
				elinewidth=2, color='r', capsize=0,
				label='w(g+)')
				axarr[0,0].errorbar(r_p, set_[1][0], yerr=set_[2][0],
				elinewidth=2, color='g', capsize=0,
				label='w(gx)', alpha=0.5)
				axarr[0,1].errorbar(r_p, set_[0][1], yerr=set_[2][1],
				elinewidth=2, color='b', capsize=0,
				label='w(g+)')
				axarr[0,1].errorbar(r_p, set_[1][1], yerr=set_[2][1],
				elinewidth=2, color='g', capsize=0,
				label='w(gx)', alpha=0.5)
				axarr[1,0].errorbar(r_p, set_[0][2], yerr=set_[2][2],
				elinewidth=2, color='r', capsize=0,
				label='w(g+)')
				axarr[1,0].errorbar(r_p, set_[1][2], yerr=set_[2][2],
				elinewidth=2, color='g', capsize=0,
				label='w(gx)', alpha=0.5)
				axarr[1,1].errorbar(r_p, set_[0][3], yerr=set_[2][3],
				elinewidth=2, color='b', capsize=0,
				label='w(g+)')
				axarr[1,1].errorbar(r_p, set_[1][3], yerr=set_[2][3],
				elinewidth=2, color='g', capsize=0,
				label='w(gx)', alpha=0.5)
			arr_ind = [(0,0), (0,1), (1,0), (1,1)]
			for i, ind in enumerate(arr_ind):
				a = axarr[ind]
				a.set_xscale('log')
				a.set_xlim(0.25,70)
				a.set_ylim(-0.5,0.4)
				a.plot(x, [0]*len(x), lw=2, ls='--', color='c')
				# a.set_xlabel('Comoving transverse separation (Mpc/h)')
				# a.set_ylabel('Correlations')
				a.set_title('%s'%wcorrIDs[i], fontsize=12)
				a.legend(loc='upper right')
				a.grid()
			plt.setp([a.get_xticklabels() for a in axarr[0, :]], visible=False)
			plt.setp([a.get_yticklabels() for a in axarr[:, 1]], visible=False)
			# plt.setp([a.get_xlabels() for a in axarr[:, 1]], visible=False)
			axarr[1,0].set_xlabel('Comoving transverse separation (Mpc/h)')
			axarr[1,0].set_ylabel('Correlations')
			ZC = np.loadtxt(join(files_path, 'ZC_cuts'), delimiter=',')
			axarr[1,1].set_xlabel('Cuts: z%s, c%s'%(ZC[0],ZC[1]))

			plotsDir = join(files_path, 'Plots')
			if not isdir(plotsDir):
				mkdir(plotsDir)

			if 'largePi' in wcorrOutputs[0]:
				outimg = join(plotsDir, '%swcorr_z%s_c%s_largePi.pdf'%(prefix[j],ZC[0],ZC[1]))
			else:
				outimg = join(plotsDir, '%swcorr_z%s_c%s.pdf'%(prefix[j],ZC[0],ZC[1]))
			f.savefig(outimg)
			try:
				plt.show()
			except RuntimeError:
				print("can't show plot :(")

		return wcorrOutputs

	def chiFunc(self, y):
		return chi2.pdf(y, 10)

	def normFunc(self, y):
		return stat.norm(0,1).pdf(y)

	def chi2(self, path2data, expec):
		filesList = np.array(listdir(path2data))
		wcorrData = np.array(['_vs_' in x for x in filesList])
		covarData = np.array(['covar' in x for x in filesList])
		wcorrList = filesList[wcorrData]
		covarList = filesList[covarData]
		[print(i,wcorrList[j]) for j,i in enumerate(covarList)]
		# [print(i) for i in covarList]

		dataArr = np.array([np.loadtxt(join(path2data, i),skiprows=1) for i in wcorrList])
		dataArr = np.array([[i[:,1], i[:,2], i[:,3], i[:,4]] for i in dataArr])
		pVals = []
		chi2s = []
		xSigma = []

		for j, data in enumerate(dataArr):
			plus,perr,cross,xerr = data[0],data[1],data[2],data[3]
			plusChi_i = ((plus-expec)/perr)**2
			crossChi_i = ((cross-expec)/xerr)**2
			chi2_pl = np.sum(plusChi_i)
			chi2_cr = np.sum(crossChi_i)
			intgrl_pl = scint.quad(self.chiFunc, chi2_pl, np.inf)
			intgrl_cr = scint.quad(self.chiFunc, chi2_cr, np.inf)
			pVal_pl = intgrl_pl[0]
			pVal_cr = intgrl_cr[0]
			pVal = ['%.5f'%pVal_pl, '%.5f'%pVal_cr]
			chi2 = ['%.5f'%chi2_pl, '%.5f'%chi2_cr]
			chi2s.append(chi2)
			pVals.append(pVal)
			pvals = np.array([pVal_pl,pVal_cr])
			x_s = abs(stat.norm.interval((1-pvals), loc=0, scale=1)[0])
			xSigma.append(x_s)
			# print("p's (pl,cr): %.5f, %.5f"%(pvals[0],pvals[1]))
			# print("xsigma's (pl,cr): %.5f, %.5f"%(x_s[0],x_s[1]))

		# CALC & SAVE CHI^2 FROM COVARIANCE MATRIX
		y = [0,4,8,12,2,6,10,14,1,5,9,13,3,7,11,15] # re-order covariance matrices
		covarList = covarList[y]
		covLists = [covarList[:8],covarList[8:]]
		for halfList in covLists:
			for j,covar in enumerate(halfList): # assert ordering matches wcorr files
				assert covar[7:] in wcorrList[j], 'mismatched signals & covariance matrices'
				if 'Pi' in wcorrList[j]:
					assert 'Pi' in covar[7:], 'mismatched signals & covariance matrices'
		covarArr = np.array([np.loadtxt(join(path2data, i),skiprows=1) for i in covarList])
		covarSigma = []
		for i,cov in enumerate(covarArr[:8]):
			cov = np.mat(cov)
			invCov = np.linalg.inv(cov)
			wgp = np.array(dataArr[i][[0]]).T[:,0]
			chi = np.matmul((np.matmul(wgp.T,invCov)), wgp)
			fchi = float(chi)
			p_val = scint.quad(self.chiFunc, fchi, np.inf)[0]
			xs = abs(stat.norm.interval((1-p_val), loc=0, scale=1)[0])
			covarSigma.append([fchi,p_val,xs])
		for i,cov in enumerate(covarArr[:8]):
			cov = np.mat(cov)
			invCov = np.linalg.inv(cov)
			wgx = np.array(dataArr[i][[2]]).T[:,0]
			chi = np.matmul((np.matmul(wgx.T,invCov)), wgx)
			fchi = float(chi)
			p_val = scint.quad(self.chiFunc, fchi, np.inf)[0]
			xs = abs(stat.norm.interval((1-p_val), loc=0, scale=1)[0])
			covarSigma.append([fchi,p_val,xs])

		pVals, chi2s, xSigma, wcorrList, covarSigma = map(lambda x: np.array(x),[pVals, chi2s, xSigma, wcorrList, covarSigma])

		chi2Stats = np.column_stack((wcorrList,chi2s[:,0],pVals[:,0],xSigma[:,0],chi2s[:,1],pVals[:,1],xSigma[:,1],covarSigma[:8][:,0],covarSigma[:8][:,1],covarSigma[:8][:,2],covarSigma[8:][:,0],covarSigma[8:][:,1],covarSigma[8:][:,2]))

		ascii.write(chi2Stats, join(path2data,'..','chi2'), delimiter='\t', names=['dataset','chi^2(plus)','p-val(plus)','x-sigma(plus)','chi^2(cross)','p-val(cross)','x-sigma(cross)','fullcovarChi2(plus)','fcPval(plus)','fcSigma(plus)','fcChi2(cross)','fcPval(cross)','fcSigma(cross)'])

		return None

	def patch_data(self, patchSize, *bitmask_):
		# find survey area
		nside = 2048
		fullSky = 41252.96 # square degrees
		npix = hp.nside2npix(nside)
		pixar = fullSky/npix
		ra = self.data['RA_1']
		dec = self.data['DEC_1']
		theta = np.deg2rad(90.-dec)
		phi = np.deg2rad(ra)
		pixIDs = hp.ang2pix(nside,theta,phi,nest=False)
		GKmap = np.bincount(pixIDs,minlength=npix)
		GKskyFrac = len(GKmap[GKmap!=0])
		nonzeropix = GKskyFrac
		GKskyFrac /= npix
		GKskyFrac *= fullSky
		print('Survey area: %.2f deg^2'%GKskyFrac)

		# find masked pixel IDs
		kidsBitmap = hp.read_map('/share/splinter/hj/PhD/KiDS_counts_N2048.fits', dtype=int)
		bitmask_cut = [True]*len(kidsBitmap)
		if bitmask_[0] != None:
			bitmask_ = bitmask_[0]
			for i in np.arange(0,len(bitmask_)):
				# construct bitmask cut
				bitmask_cut &= np.where(bitmask_[i] & kidsBitmap == bitmask_[i], False, True)
		lostpixIDs = [j for j,b in enumerate(bitmask_cut) if b==False]
		print('Lost npix, fraction of area: %s, %s'%(len(lostpixIDs),len(lostpixIDs)/nonzeropix))
		thetaPhis = hp.pix2ang(nside,lostpixIDs)
		# lost pixel coords;
		lostpixra,lostpixdec = np.rad2deg(thetaPhis[1]),(90.-np.rad2deg(thetaPhis[0]))
		del kidsBitmap
		gc.collect()

		# divide catalog.data into patches of 2-3 sqdeg
		raHist = np.histogram(ra, bins=100)
		decHist = np.histogram(dec, bins=100)
		raCounts, raEdges = raHist
		decCounts, decEdges = decHist
		Counts, Edges = [raCounts, decCounts], [raEdges, decEdges]
		Lowers = [[],[]]
		Uppers = [[],[]]
		# find mins/maxs in ra/dec of surveyed areas
		for i, count in enumerate(Counts):
			while len(count)!=0:
				nonz = np.nonzero(count)[0] # index of 1st populated bin
				Lowers[i].append(Edges[i][nonz[0]]) # corresponding min coord
				if 0 in count:
					leadz = list(count).index(0) # index of 1st empty bin
					Uppers[i].append(Edges[i][leadz]) # corresp. max coord
					# shorten counts/edges, & repeat...
					count = count[leadz:]
					Edges[i] = Edges[i][leadz:]
					nonz = np.nonzero(count)[0]
					count = count[nonz[0]:]
					Edges[i] = Edges[i][nonz[0]:]
				else: # ...until absolute maxs in ra/dec
					Uppers[i].append(Edges[i][-1])
					count=[]

		raLs,raUs,decLs,decUs = map(lambda x: np.array(x),[Lowers[0], Uppers[0], Lowers[1], Uppers[1]])
		# ranges in ra/dec
		deltaR = raUs-raLs
		deltaD = decUs-decLs
		RDratio = deltaR/deltaD
		# use ratio to determine integer nos. of 'columns/rows' of patches
		dLen = np.array([1]*len(RDratio))
		rLen = dLen*np.round(RDratio)
		rPatchside = deltaR/rLen
		dPatchside = deltaD/dLen
		patchAr = rPatchside*dPatchside
		initDiff = abs(patchAr-patchSize)

		while any(abs(patchAr-patchSize)>0.5):
			dLen += 1
			rLen = dLen*np.round(RDratio)
			rPatchside = deltaR/rLen
			dPatchside = deltaD/dLen
			patchAr = rPatchside*dPatchside
			print('patchArs :',patchAr)
			newDiff = abs(patchAr-patchSize)
			if newDiff[0]>initDiff[0]:
				print('MISSED PATCH-AREA TARGET')
				break
				# sys.exit()
		[print('Patch areas (sqdeg): %.2f'%i) for i in patchAr] 
		print('rSides (#,deg): ',rLen,rPatchside)
		print('dSides (#,deg): ',dLen,dPatchside)
		patch_Ars = np.array([[i]*(dLen[j]-1)*(rLen[j]-1) for j,i in enumerate(patchAr)]).flatten()

		# contsruct patch edges = 'ra/decPatches'
		raLims = np.column_stack((raLs,raUs))
		decLims = np.column_stack((decLs,decUs))

		raPatches = [np.linspace(raLims[i][0],raLims[i][1],num=rLen[i]) for i in np.arange(0,len(raLims))]
		decPatches = [np.linspace(decLims[i][0],decLims[i][1],num=dLen[i]) for i in np.arange(0,len(decLims))]
		raPatches,decPatches = map(lambda x: np.array(x),[raPatches,decPatches])

		# create column/row cuts from patch edges
		raCuts = []
		decCuts = []
		pixraCuts = []
		pixdecCuts = []
		for j in np.arange(0,len(raPatches)):
			raCuts.append(np.array([np.where((ra>=raPatches[j][i])&(ra<=raPatches[j][i+1]),True,False) for i in np.arange(0,len(raPatches[j])-1)]))
			# AND DEFINE FROM lostpixra
			pixraCuts.append(np.array([np.where((lostpixra>=raPatches[j][i])&(lostpixra<=raPatches[j][i+1]),True,False) for i in np.arange(0,len(raPatches[j])-1)]))
		for j in np.arange(0,len(decPatches)):
			decCuts.append(np.array([np.where((dec>=decPatches[j][i])&(dec<=decPatches[j][i+1]),True,False) for i in np.arange(0,len(decPatches[j])-1)]))
			# AND DEFINE FROM lostpixdec
			pixdecCuts.append(np.array([np.where((lostpixdec>=decPatches[j][i])&(lostpixdec<=decPatches[j][i+1]),True,False) for i in np.arange(0,len(decPatches[j])-1)]))

		raCuts,decCuts,pixraCuts,pixdecCuts = map(lambda x: np.array(x), [raCuts, decCuts,pixraCuts,pixdecCuts])
		raCuts,decCuts,pixraCuts,pixdecCuts = map(lambda x: x.reshape(-1,x.shape[-1]),[raCuts,decCuts,pixraCuts,pixdecCuts]) # flatten 3 cut-arrays (from 3 survey regions) into 1

		# combine into patch-cuts
		patchCuts = []
		pixpatchCuts = []
		for j in decCuts:
			[patchCuts.append(i&j) for i in raCuts]
		for j in pixdecCuts:
			[pixpatchCuts.append(i&j) for i in pixraCuts]
		patchCuts = np.array(patchCuts)
		pixpatchCuts = np.array(pixpatchCuts)
		print('pixpatchCuts shape: (%s, %s)'%pixpatchCuts.shape)
		assert patchCuts.shape[0] == raCuts.shape[0]*decCuts.shape[0], 'patch-cuts broken'

		# combine patch & z/colour cuts
		highzR_pcuts = [(self.zcut&self.redcut&self.bitmaskcut&pc) for pc in patchCuts]
		highzB_pcuts = [(self.zcut&self.bluecut&self.bitmaskcut&pc) for pc in patchCuts]
		lowzR_pcuts = [(self.zcut_r&self.redcut&self.bitmaskcut&pc) for pc in patchCuts]
		lowzB_pcuts = [(self.zcut_r&self.bluecut&self.bitmaskcut&pc) for pc in patchCuts]

		highzR_pcuts,highzB_pcuts,lowzR_pcuts,lowzB_pcuts = map(lambda x: np.array(x),[highzR_pcuts,highzB_pcuts,lowzR_pcuts,lowzB_pcuts])

		# cut data into 4xpatch-arrays, each element of which is a fits-table
		hizR_patches,hizB_patches,lozR_patches,lozB_patches = map(lambda x: np.array([self.data[pc] for pc in x]),[highzR_pcuts,highzB_pcuts,lowzR_pcuts,lowzB_pcuts])

		del highzR_pcuts,highzB_pcuts,lowzR_pcuts,lowzB_pcuts
		gc.collect()

		self.patchedData = np.array([hizR_patches,hizB_patches,lozR_patches,lozB_patches])

		# count lost pixels within each patch for weighting
		npixLost = np.array([np.count_nonzero(i) for i in pixpatchCuts])
		pArLost = npixLost*pixar
		weights = 1-(pArLost/patch_Ars)
		self.patchWeights = np.where(weights>0,weights,0)
		print(self.patchWeights)

		return self.patchedData, self.patchWeights

	def save_patches(self, patch, outfile_root, label, p_num):
		patchDir = join(outfile_root,label)
		if not isdir(patchDir):
			mkdir(patchDir)
		patchName = join(patchDir,label+'%spatch.asc'%str(p_num).zfill(2))
		ascii.write(patch, patchName, delimiter='\t', names=['#RA/rad', '#DEC/rad', '#comov_dist/Mpc/h', '#e1', '#e2', '#e_weight'])
		return patchDir

	def wcorr_patches(self, patchDir, rp_bins, rp_lims, los_bins, los_lim, nproc, largePi):
		patches = [patch for patch in listdir(patchDir) if 'patch' in patch]
		density = [d for d in listdir(patchDir) if d.endswith('Z.asc')][0]
		dCount = len(np.loadtxt(join(patchDir,density)))
		print('density count: %d'%dCount)
		for i,p in enumerate(patches):
			pCount = len(np.loadtxt(join(patchDir,p)))
			print("patch %s, popn %s"%(i,pCount))
			os.system('/share/splinter/hj/PhD/CosmoFisherForecast/obstools/wcorr %s %s %s %s %s %s %s %s %s %s %s %s 0 0'%(patchDir,density,dCount,p,pCount,rp_bins,rp_lims[0],rp_lims[1],los_bins,los_lim,p[:-9],nproc))
			if largePi:
				os.system('/share/splinter/hj/PhD/CosmoFisherForecast/obstools/wcorr %s %s %s %s %s %s %s %s %s %s %s_largePi %s 1 0'%(patchDir,density,dCount,p,pCount,rp_bins,rp_lims[0],rp_lims[1],los_bins,los_lim,p[:-9],nproc))
			del pCount
			gc.collect()
			#break

	def bootstrap_signals(self, patchDir, patchWeights, largePi):
		pwcorrs = [x for x in listdir(patchDir) if ('.dat' in x)&('Pi' not in x)]
		if largePi:
			pwcorrs = [x for x in listdir(patchDir) if 'Pi' in x]
		psigs = []
		for x in pwcorrs:
			path = join(patchDir, x)
			data = np.array(np.loadtxt(path))
			psigs.append([data[:,3],data[:,4]]) # [+, x]
		psigs = np.array(psigs)
		BTsignals = astat.bootstrap(psigs, bootnum=100000)
		# construct errors for each bin in r_p, for + & x corrs
		wgplus = BTsignals[:,:,0,:]
		wgcross = BTsignals[:,:,1,:]
		# shape = (BTs, patch-signal, rp bins)

		# calculate mean over patches (weighted)
		Pmeans = np.average(wgplus,axis=1, weights=patchWeights)
		Xmeans = np.average(wgcross,axis=1, weights=patchWeights)
		# shape = (BTs, mean-signal-in-rp-bin)

		# calculate covariance matrix & corr-coeffs (for +)
		covP = np.cov(Pmeans,rowvar=0)
		corrcoeffP = np.corrcoef(Pmeans,rowvar=0)
		covX = np.cov(Xmeans,rowvar=0)
		corrcoeffX = np.corrcoef(Xmeans,rowvar=0)

		# calculate stdev over BT-realis'ns
		Pstds = np.std(Pmeans,axis=0)
		Xstds = np.std(Xmeans,axis=0)
		# shape = (stdev-on-means-in-rp-bins)

		BTstds = np.column_stack((Pstds,Xstds))
		label = basename(normpath(patchDir))
		BTerrs_out = join(patchDir,'..','BTerrs_%s'%label)
		if largePi:
			BTerrs_out = join(patchDir,'..','BTerrs_%s_largePi'%label)
		ascii.write(BTstds, BTerrs_out, delimiter='\t', names=['#w(g+)err','#w(gx)err'])
		cov_combos = [[covP,'P'],[covX,'X']]

		toplotDir = join(patchDir,'../to_plot')
		if not isdir(toplotDir):
			mkdir(toplotDir)
		if not largePi:
			corrName = join(toplotDir,'corrcoeff_%s'%label)
			ascii.write(corrcoeffP, corrName, delimiter='\t')

			for covs in cov_combos:
				covName = join(toplotDir,'covar%s_%s'%(covs[1],label))
				ascii.write(covs[0], covName, delimiter='\t')
		else:
			for covs in cov_combos:
				covName = join(toplotDir,'covar%s_%s_largePi'%(covs[1],label))
				ascii.write(covs[0], covName, delimiter='\t')
		return None

	def map_test(self, catalogs):
		npix = hp.nside2npix(128)
		hmap = [0]*npix
		for cat in catalogs:
			ra = cat['RA_1']
			dec = cat['DEC_1']
			theta = np.deg2rad(90.-dec)
			phi = np.deg2rad(ra)
			pix = hp.ang2pix(128,theta,phi)
			hmap += np.bincount(pix, minlength=npix)
		hp.write_map('patchTest_map.fits',hmap)
		# plt.savefig('/share/splinter/hj/PhD/patchTest.pdf')
		return None


class RandomCatalogue(RealCatalogue):

	def __init__(self, path):
		"""""
		read-in catalogue

		"""""
		self.path = path
		hdulist = fits.open(path)
		self.data = hdulist[1].data
		self.columns = hdulist[1].columns.names
		self.labels = ['rand_highZ', 'rand_lowZ']

	def cut_data(self, z_, len_reals, z_reals): 
		"""""
		cut catalogue into redshift subsamples

		"""""
		assert 'RA' in self.columns, "'RA' not in columns, see column headers: "+ str(self.columns)
		assert 'DEC' in self.columns, "'DEC' not in columns, see column headers: "+ str(self.columns)
		assert 'Z' in self.columns, "'Z' not in columns, see column headers: "+ str(self.columns)
		assert 'RAND_NUM' in self.columns, "'RAND_NUM' not in columns, see column headers: "+ str(self.columns)

		# cut down (randomly) for correlation
		randNum = self.data['RAND_NUM']
		current = len(randNum)
		target = len_reals*10
		fraction = target/current
		randCut = (randNum > fraction) & (randNum <= 2*fraction)
		self.data = self.data[randCut]
		print('Randoms cut down from %s objects to %s' % (len(randNum), len(self.data)))

		z = self.data['z']
		pre_z_cut = (z >= z_reals.min()) & (z <= z_reals.max()) # GET RID OF THIS CUT??
		self.data = self.data[pre_z_cut]
		z = self.data['z']

		if z_ != None:
			z_cut = np.array((z > z_))
			z_cut_r = ~z_cut
		else:
			z_cut = np.array([True]*len(self.data))
			z_cut_r = z_cut
			print('highZ catalog == lowZ catalog')

		self.highz = self.data[z_cut]
		self.lowz = self.data[z_cut_r]
		self.samplecounts = [len(self.highz), len(self.lowz)]

		[print('# objects %s: \t'%self.labels[i], v) for i, v in enumerate(self.samplecounts)]

	def cut_columns(self, subsample, h): 
		"""""
		take subsample data 
		& isolate columns for wcorr

		"""""
		assert 'RA' in self.columns, "'RA' not in columns, see column headers: "+ str(self.columns)
		assert 'DEC' in self.columns, "'DEC' not in columns, see column headers: "+ str(self.columns)
		assert 'Z' in self.columns, "'Z' not in columns, see column headers: "+ str(self.columns)

		table = subsample
		RA = np.deg2rad(table['RA'])
		DEC = np.deg2rad(table['DEC'])
		Z = table['Z']
		e1 = 2*np.random.random(len(table))
		e2 = e1
		e2 *= -1 # for RA increasing leftward, c.f. x-axis increasing rightward
		e_weight = np.array([1]*len(table))
		comov = Planck13.comoving_distance(Z)
		comov *= h
		new_table = np.column_stack((RA, DEC, comov, e1, e2, e_weight))
		return new_table

if __name__ == "__main__":
	parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
	parser.add_argument(
	'Catalog',
	help='full path of REAL catalogue to be sampled into ascii table(s)')
	parser.add_argument(
	'Path',
	help='full path of destination directory for subsample ascii catalogues, where further directories will be created and appended with "_z_<z_cut>_c_<colour_cut>" if applicable. ***If using -plotNow, give full path to wcorr output directory***')
	parser.add_argument(
	'-Random',
	help="optional; path to RANDOM catalogue to be correspondingly sampled",
	default=None)
	parser.add_argument(
	'-pgm_cut',
	type=np.float32,
	help='shear polarizability cut, defaults to 0.1',
	default=0.1)
	parser.add_argument(
	'-zCut',
	type=np.float32,
	help='lowZ vs. highZ redshift threshold, between 0 - 0.5. Omit for no redshift cut',
	default=None)
	parser.add_argument(
	'-cCut',
	type=np.float32,
	help='red vs. blue colour threshold, between 0 - 1.4 (meaningfully, between approx 0.7 - 1.1). Omit for no colour cut',
	default=None)
	parser.add_argument(
	'-bitmaskCut',
	nargs='*',
	type=int,
	help='list of bitmask IDs (powers of 2) to exclude from catalogue, eg. text-file w/ ROWS; 4, 16, 4096...etc...',
	default=None)
	parser.add_argument(
	'-H',
	type=np.float32,
	help='reduced Planck constant, defaults to 0.7',
	default=0.7)
	parser.add_argument(
	'-rpBins',
	type=int,
	help='specify no. of (log-spaced) bins in comoving transverse separation r_p (Mpc/h), for measurement of density-shape correlations. Defaults to 10',
	default=10)
	parser.add_argument(
	'-rpLims',
	nargs=2,
	type=np.float32,
	help='specify upper & lower (2 args, space-separated) limit in comoving transverse separation r_p (Mpc/h), for measurement of density-shape correlations. Defaults to 0.3, 60 Mpc/h',
	default=[0.3, 60])
	parser.add_argument(
	'-losBins',
	type=int,
	help='specify no. of bins (positive branch) in comoving line-of-sight separation \Pi (Mpc/h), for measurement of density-shape correlations. Defaults to 15; i.e. 30 bins in total',
	default=15)
	parser.add_argument(
	'-losLim',
	type=np.float32,
	help='specify cut-off in comoving line-of-sight separation \Pi (Mpc/h), for measurement of density-shape correlations. Defaults to 60; s/t range is -60 to 60 Mpc/h',
	default=60)
	parser.add_argument(
	'-nproc',
	type=int,
	help='no. processors to be used in correlation measurement, default = 12',
	default=12)
	parser.add_argument(
	'-largePi',
	type=int,
	choices=[0,1],
	help='specify regular (0) or regular + large-Pi systematics tests (1), defaults to 1',
	default=0)
	parser.add_argument(
	'-wcorr',
	type=int,
	choices=[0,1],
	help='initiate wcorr density-shape correlation measurements (1), or not (0), defaults to 0',
	default=0)
	parser.add_argument(
	'-notes',
	help='notes on any changed wcorr parameters, for appendage to directory name',
	default=None)
	parser.add_argument(
	'-plot',
	help='plot data & save figure after correlations completed (1), or not (0), defaults to 1',
	choices=[0,1],
	type=int,
	default=1)
	parser.add_argument(
	'-plotNow',
	help='plot ALREADY EXISTING correlation data (1), having given arg="Path" as the path to the .dat files (Catalog arg must still be path of readable .fits catalog). Bypasses all other sampling functions. Defaults to 0',
	choices=[0,1],
	type=int,
	default=0)
	parser.add_argument(
	'-chiSqu',
	help='calc chi^2 stats for ALREADY EXISTING correlation data (1), having given arg="Path" as the path to the .dat files (Catalog arg must still be path of readable .fits catalog). Bypasses all other sampling functions. Defaults to 0',
	choices=[0,1],
	type=int,
	default=0)
	parser.add_argument(
	'-expec',
	help='expectation values for chi^2 statistics, defaults to zeros at all points',
	default=0)
	parser.add_argument(
	'-bootstrap',
	type=int,
	choices=[0,1],
	help='perform bootstrap error determination (1) or not (0), defaults to 1',
	default=1)
	parser.add_argument(
	'-patchSize',
	help='preferred mean patch size (deg^2) for bootstrap error determination, defaults to 2.5',
	type=np.float32,
	default=2.5)
	args = parser.parse_args()

	catalog = RealCatalogue(args.Catalog)

	if args.plotNow:
		# plot .dat files, returning filename-list
		print('PLOTTING')
		wcorrOuts = catalog.plot_wcorr(args.Path, catalog.wcorrLabels, args.bootstrap, 0)
		largePi_outs = [basename(normpath(out[:-4] + '_largePi.dat')) for out in wcorrOuts]
		# check for largePi .dat files
		isIn = [i in listdir(args.Path) for i in largePi_outs]
		uniq = np.unique(isIn)
		if uniq.all() == True:
			IDs = [outs[6:-4] for outs in largePi_outs]
			a = catalog.plot_wcorr(args.Path, IDs, args.bootstrap, 1)

		if args.chiSqu:
			print('CALC CHI^2')
			# calculate chi^2 statistics & save to ascii
			catalog.chi2(join(args.Path,'to_plot'), args.expec)
			sys.exit()
		sys.exit()

	if args.chiSqu:
		print('CALC CHI^2')
		# calculate chi^2 statistics & save to csv
		catalog.chi2(join(args.Path,'to_plot'), args.expec)
		sys.exit()

	catalog.cut_data(args.pgm_cut, args.zCut, args.cCut, args.bitmaskCut)
	samples = [catalog.highz_R,catalog.highz_B,catalog.lowz_R,catalog.lowz_B,catalog.highz,catalog.lowz]
	cuts = 'z-cut: %s\t colour-cut (g-i): %s'%(args.zCut,args.cCut)
	sample_numbers = [cuts]
	outfile_root = join(args.Path,'Wcorr')

	for i, sample in enumerate(samples):
		new_table = catalog.cut_columns(sample, args.H)
		sample_num = catalog.save_tables(new_table, outfile_root, catalog.labels[i], args.zCut, args.cCut, args.notes)
		sample_numbers.append(sample_num)

	File = join(catalog.new_root, 'Sample_popns')
	Write = open(File, "w")
	Text = "\n".join(sample_numbers)
	Write.write(str(Text))
	Write.close()

	if args.bootstrap:
		# patchData.shape = (4 subsamples, N patches)
		patchData, patchWeights = catalog.patch_data(args.patchSize, args.bitmaskCut)
		# print('MAPPING')
		# catalog.map_test(patchData[0])
		# print('MAPPED')
		for i,sam in enumerate(patchData):
			for j,p in enumerate(sam):
				new_p = catalog.cut_columns(p, args.H)
				pDir = catalog.save_patches(new_p, catalog.new_root, catalog.labels[i], j) # save_patches returns str(patchDir)
			# copy density samples into patchDirs for wcorr
			[os.system('cp %s %s'%(join(catalog.new_root,catalog.labels[4]+'.asc'),join(catalog.new_root,catalog.labels[d],catalog.labels[4]+'.asc'))) for d in [0,1]]
			[os.system('cp %s %s'%(join(catalog.new_root,catalog.labels[5]+'.asc'),join(catalog.new_root,catalog.labels[d],catalog.labels[5]+'.asc'))) for d in [2,3]]
			catalog.wcorr_patches(pDir, args.rpBins, args.rpLims, args.losBins, args.losLim, args.nproc, args.largePi)
			catalog.bootstrap_signals(pDir, patchWeights, 0)
			if args.largePi:
				catalog.bootstrap_signals(pDir, patchWeights, 1)

	catalog.make_combos()
	catalog.prep_wcorr(catalog.new_root,catalog.wcorr_combos,args.rpBins,args.rpLims,args.losBins,args.losLim,args.nproc,args.largePi,'real_wcorr')

	if args.wcorr:
		list_dir = np.array(listdir(catalog.new_root))
		shells = np.array([i.endswith('.sh') for i in list_dir])
		r_shells = np.array([i.startswith('real') for i in list_dir])
		list_dir = list_dir[(shells&r_shells)]
		[os.system('qsub '+ join(catalog.new_root, shell)) for shell in list_dir]

	if args.Random != None:
		catalog2 = RandomCatalogue(args.Random)
		catalog2.cut_data(args.zCut, catalog.pre_count, catalog.pre_z)
		samples = [catalog2.highz, catalog2.lowz]
		cuts = 'z-cut: %s'%args.zCut
		sample_numbers = [cuts]

		for i, sample in enumerate(samples):
			new_table = catalog2.cut_columns(sample, args.H)
			sample_num = catalog2.save_tables(new_table,outfile_root,catalog2.labels[i],args.zCut,args.cCut,args.notes)
			sample_numbers.append(sample_num)

		File = join(catalog.new_root, 'Sample_rand_popns')
		Write = open(File, "w")
		Text = "\n".join(sample_numbers)
		Write.write(str(Text))
		Write.close()

		rand_combos = [
		[catalog2.labels[0]+'.asc', catalog2.samplecounts[0], catalog.labels[0]+'.asc', catalog.samplecounts[0], 'rand_'+catalog.wcorrLabels[0]],
		[catalog2.labels[0]+'.asc', catalog2.samplecounts[0], catalog.labels[1]+'.asc', catalog.samplecounts[1], 'rand_'+catalog.wcorrLabels[1]],
		[catalog2.labels[1]+'.asc', catalog2.samplecounts[1], catalog.labels[2]+'.asc', catalog.samplecounts[2], 'rand_'+catalog.wcorrLabels[2]],
		[catalog2.labels[1]+'.asc', catalog2.samplecounts[1], catalog.labels[3]+'.asc', catalog.samplecounts[3], 'rand_'+catalog.wcorrLabels[3]]
		]

		catalog2.prep_wcorr(catalog.new_root, rand_combos, args.rpBins, args.rpLims, args.losBins, args.losLim, args.nproc, args.largePi, 'rand_wcorr')

		if args.plot:
			with open(join(catalog.new_root, 'rand_wcorr.sh'), 'a') as script:
				script.write(
				'\npython /share/splinter/hj/PhD/catalog_sampler.py %s %s -plotNow 1 -chiSqu 1'%(args.Catalog, catalog.new_root)
				)
				script.write('\n')

		if args.wcorr:
			list_dir = np.array(listdir(catalog.new_root))
			shells = np.array([i.endswith('.sh') for i in list_dir])
			r_shells = np.array([i.startswith('rand') for i in list_dir])
			list_dir = list_dir[(shells&r_shells)]
			[os.system('qsub '+ join(catalog.new_root, shell)) for shell in list_dir]

























