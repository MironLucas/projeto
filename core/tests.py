from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

from .views import _resolver_periodo


def _local(*args):
    return timezone.make_aware(datetime(*args))


def _congelar_em(*args):
    return mock.patch('core.views.timezone.now', return_value=_local(*args))


def _fmt(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


class ResolverPeriodoTests(SimpleTestCase):
    def test_hoje_compara_com_ontem_ate_a_mesma_hora(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('hoje', None, None)
        self.assertEqual(_fmt(p.desde), '24/09/2026 00:00')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '23/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '23/09/2026 11:25')
        self.assertEqual(p.label_comparacao, 'vs. ontem até 11:25')

    def test_semana_compara_ate_o_mesmo_dia_e_hora_da_semana_passada(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('semana', None, None)
        self.assertEqual(_fmt(p.desde), '21/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '14/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '17/09/2026 11:25')
        self.assertEqual(p.label_comparacao, 'vs. semana passada até qui 11:25')

    def test_mes_compara_ate_o_mesmo_dia_e_hora_do_mes_passado(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.desde), '01/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '01/08/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '24/08/2026 11:25')
        self.assertEqual(p.label_comparacao, 'vs. mês passado até 24/08 11:25')

    def test_mes_no_dia_31_usa_o_ultimo_dia_do_mes_anterior(self):
        with _congelar_em(2026, 3, 31, 9, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_ate), '28/02/2026 09:00')

    def test_mes_em_janeiro_compara_com_dezembro_do_ano_anterior(self):
        with _congelar_em(2026, 1, 10, 8, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_desde), '01/12/2025 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '10/12/2025 08:00')

    def test_mes_passado_compara_meses_completos(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes_passado', None, None)
        self.assertEqual(_fmt(p.desde), '01/08/2026 00:00')
        self.assertEqual(_fmt(p.ate), '31/08/2026 23:59')
        self.assertEqual(_fmt(p.anterior_desde), '01/07/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '31/07/2026 23:59')

    def test_periodo_que_termina_hoje_compara_ate_a_mesma_hora(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-09-20', '2026-09-24')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '15/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '19/09/2026 11:25')
        self.assertEqual(p.label_comparacao, 'vs. 5 dias anteriores')

    def test_periodo_com_datas_invertidas_e_corrigido(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-08-15', '2026-08-01')
        self.assertEqual(p.label, '01/08/2026 – 15/08/2026')

    def test_periodo_invalido_volta_para_hoje(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', 'xx', 'yy')
        self.assertEqual(p.chave, 'hoje')
